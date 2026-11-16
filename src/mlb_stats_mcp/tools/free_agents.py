"""Free agent tool: the latest offseason's free agent class, best first by WAR."""

from __future__ import annotations

from typing_extensions import NotRequired, TypedDict

from ..config import CacheTTL, FreeAgency, Limits
from ..mlb import endpoints, get_client
from . import advanced
from .common import (
    JSON,
    FreeAgentStatus,
    Position,
    clamp,
    current_season,
    dig,
    season_cache_ttl,
)
from .teams import resolve_team

ALL_STATUSES = "all"
SIGNED = "signed"

# The /people fields needed to rank free agents. Without this filter MLB sends every
# sabermetric (~2 KB per player); with it, just WAR and age.
_WAR_RESPONSE_FIELDS = "people,id,currentAge,stats,type,group,displayName,splits,team,stat,war"


class FreeAgent(TypedDict):
    player_id: int
    name: str | None
    position: str | None
    age: int | None
    war: float | None  # in the class's season, hitting and pitching combined
    former_team: str | None
    new_team: str | None  # null while unsigned
    declared_date: str | None  # when they became a free agent
    signed_date: str | None  # not recorded for every signing
    notes: str | None  # e.g. "Club Option Declined", "Claimed off waivers."


class FreeAgentList(TypedDict):
    """Free agents matching the filters, highest WAR first (players without MLB stats last)."""

    season: int  # the class: players who became free agents after this season
    status: FreeAgentStatus
    position: Position | None
    team: str | None
    total_matching: int
    free_agents: list[FreeAgent]
    note: NotRequired[str]


# ------------------------------------------------------------------- helpers --


async def _free_agent_class(season: int) -> list[JSON]:
    data = await get_client().get(
        endpoints.FREE_AGENTS, {"season": season}, ttl=CacheTTL.FREE_AGENTS
    )
    return data.get("freeAgents", [])


async def _latest_class(season: int | None) -> tuple[int, list[JSON]]:
    """The requested class or, by default, the newest one MLB has published."""
    if season:
        return season, await _free_agent_class(season)
    season = current_season()
    entries = await _free_agent_class(season)
    if not entries:  # this year's class only appears once the World Series ends
        season -= 1
        entries = await _free_agent_class(season)
    return season, entries


def _is_signed(entry: JSON) -> bool:
    # Every entry has a newTeam object, but it only has an id once a team signs or claims him.
    return dig(entry, "newTeam", "id") is not None


def _matches_position(entry: JSON, position: Position | None) -> bool:
    if position is None:
        return True
    group_type = FreeAgency.POSITION_TYPES_BY_GROUP.get(position)
    if group_type:
        return dig(entry, "position", "type") == group_type
    return dig(entry, "position", "abbreviation") == position


def _matches(
    entry: JSON,
    status: FreeAgentStatus,
    position: Position | None,
    team_id: int | None,
    include_minor_leaguers: bool,
) -> bool:
    if not include_minor_leaguers and entry.get("notes") == FreeAgency.MINOR_LEAGUE_NOTE:
        return False
    if status != ALL_STATUSES and _is_signed(entry) != (status == SIGNED):
        return False
    if team_id is not None and team_id not in (
        dig(entry, "originalTeam", "id"),
        dig(entry, "newTeam", "id"),
    ):
        return False
    return _matches_position(entry, position)


async def _people_with_war(player_ids: list[int], season: int) -> dict[int, JSON]:
    """Each player's age and WAR for the season, in one request."""
    if not player_ids:
        return {}
    groups = ",".join(advanced.FIELDS)  # hitting and pitching, for two-way players
    data = await get_client().get(
        endpoints.PEOPLE,
        {
            "personIds": ",".join(map(str, player_ids)),
            "hydrate": f"stats(group=[{groups}],type=[{advanced.SABERMETRICS}],season={season})",
            "fields": _WAR_RESPONSE_FIELDS,
        },
        ttl=season_cache_ttl(season),
    )
    return {person["id"]: person for person in data.get("people", [])}


def _format_free_agent(entry: JSON, person: JSON) -> FreeAgent:
    return {
        "player_id": dig(entry, "player", "id"),
        "name": dig(entry, "player", "fullName"),
        "position": dig(entry, "position", "abbreviation"),
        "age": person.get("currentAge"),
        "war": advanced.season_war(person),
        "former_team": dig(entry, "originalTeam", "name"),
        "new_team": dig(entry, "newTeam", "name"),
        "declared_date": entry.get("dateDeclared"),
        "signed_date": entry.get("dateSigned"),
        "notes": entry.get("notes"),
    }


def _best_first(free_agent: FreeAgent) -> tuple[bool, float, str]:
    war = free_agent["war"]
    return war is None, -(war or 0.0), free_agent["name"] or ""


# ---------------------------------------------------------------------- tool --


async def get_free_agents(
    status: FreeAgentStatus = "available",
    position: Position | None = None,
    team: str | None = None,
    include_minor_leaguers: bool = False,
    season: int | None = None,
    limit: int = Limits.DEFAULT_FREE_AGENTS,
) -> FreeAgentList:
    """Get MLB free agents from the latest offseason class, best first by WAR in the season
    before they became free agents. Use for "who's still available?", "best free agent
    shortstops", "where did the Mets' free agents go?" and "who has signed so far?".
    For every kind of roster move (trades, waivers, call-ups), use get_transactions.

    Args:
        status: "available" (unsigned), "signed" (signed, re-signed or claimed) or "all".
        position: e.g. "SS", "C", "CF" or "DH". "IF", "OF" and "P" match every infielder,
            outfielder or pitcher; many pitchers are listed only as "P".
        team: Only players who left or joined this team (name, abbreviation or id).
        include_minor_leaguers: Also include minor-league free agents (most have no MLB stats).
        season: The class: players who became free agents after this season. Defaults to the
            latest class.
        limit: How many to return (1-400).
    """
    resolved_team = await resolve_team(team) if team else None
    season, entries = await _latest_class(season)
    team_id = resolved_team["id"] if resolved_team else None
    matching = [
        entry
        for entry in entries
        if _matches(entry, status, position, team_id, include_minor_leaguers)
    ]

    people = await _people_with_war([dig(entry, "player", "id") for entry in matching], season)
    free_agents = sorted(
        (_format_free_agent(e, people.get(dig(e, "player", "id"), {})) for e in matching),
        key=_best_first,
    )
    shown = free_agents[: clamp(limit, 1, Limits.MAX_FREE_AGENTS)]

    result: FreeAgentList = {
        "season": season,
        "status": status,
        "position": position,
        "team": resolved_team["name"] if resolved_team else None,
        "total_matching": len(free_agents),
        "free_agents": shown,
    }
    if not free_agents:
        result["note"] = f"No free agents in the {season} class match these filters."
    elif len(shown) < len(free_agents):
        result["note"] = f"Showing the top {len(shown)} by WAR; raise limit to see more."
    return result
