"""Team tools, plus the name → team lookup other tools use."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError
from typing_extensions import TypedDict

from ..config import CacheTTL, MLBApi
from ..mlb import endpoints, get_client
from .common import JSON, RosterType, dig

# Team fields tried, in order, for an exact (case-insensitive) match.
_EXACT_MATCH_FIELDS = ("abbreviation", "name", "teamName", "clubName", "shortName")


# --------------------------------------------------------------- result types --


class Team(TypedDict):
    id: int
    name: str | None
    abbreviation: str | None
    league: str | None
    division: str | None
    venue: str | None


class TeamList(TypedDict):
    """Every MLB team, sorted by name."""

    count: int
    teams: list[Team]


class RosterPlayer(TypedDict):
    player_id: int | None
    name: str | None
    jersey: str | None
    position: str | None
    status: str | None


class Roster(TypedDict):
    team: str
    roster_type: RosterType
    count: int
    players: list[RosterPlayer]


async def _all_teams(hydrate: str | None = None) -> list[JSON]:
    data = await get_client().get(
        endpoints.TEAMS,
        {"sportId": MLBApi.SPORT_ID_MLB, "hydrate": hydrate},
        ttl=CacheTTL.STATIC,
    )
    return data.get("teams", [])


async def resolve_team(team: str) -> JSON:
    """Find a team by id, abbreviation, name, nickname or a unique part of its name."""
    query = team.strip().lower()
    teams = await _all_teams()

    if query.isdigit():
        for candidate in teams:
            if candidate["id"] == int(query):
                return candidate

    for field in _EXACT_MATCH_FIELDS:
        for candidate in teams:
            if str(candidate.get(field, "")).lower() == query:
                return candidate

    partial_matches = [t for t in teams if query in t.get("name", "").lower()]
    if len(partial_matches) == 1:
        return partial_matches[0]
    if partial_matches:
        names = ", ".join(t["name"] for t in partial_matches)
        raise ToolError(f"'{team}' is ambiguous: {names}. Be more specific.")
    raise ToolError(f"No MLB team matches '{team}'. Call list_teams to see valid teams.")


def _format_team(team: JSON) -> Team:
    return {
        "id": team["id"],
        "name": team.get("name"),
        "abbreviation": team.get("abbreviation"),
        "league": dig(team, "league", "name"),
        "division": dig(team, "division", "name"),
        "venue": dig(team, "venue", "name"),
    }


def _format_roster_entry(entry: JSON) -> RosterPlayer:
    return {
        "player_id": dig(entry, "person", "id"),
        "name": dig(entry, "person", "fullName"),
        "jersey": entry.get("jerseyNumber"),
        "position": dig(entry, "position", "abbreviation"),
        "status": dig(entry, "status", "description"),
    }


async def list_teams() -> TeamList:
    """List all 30 MLB teams with their ids, abbreviations, league, division and ballpark."""
    teams = await _all_teams(hydrate="league,division")
    formatted = [_format_team(t) for t in sorted(teams, key=lambda t: t.get("name", ""))]
    return {"count": len(formatted), "teams": formatted}


async def get_team_roster(
    team: str,
    roster_type: RosterType = "active",
    season: int | None = None,
) -> Roster:
    """Get a team's roster.

    Args:
        team: Team name, abbreviation or id, e.g. "Dodgers", "LAD" or "119".
        roster_type: "active" (26-man), "40Man", or "fullSeason" (everyone who played that season).
        season: Season year; defaults to the current one.
    """
    resolved = await resolve_team(team)
    data = await get_client().get(
        endpoints.team_roster(resolved["id"]),
        {"rosterType": roster_type, "season": season},
        ttl=CacheTTL.ROSTER,
    )
    players = [_format_roster_entry(entry) for entry in data.get("roster", [])]
    return {
        "team": resolved["name"],
        "roster_type": roster_type,
        "count": len(players),
        "players": players,
    }
