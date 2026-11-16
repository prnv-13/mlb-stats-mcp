"""Player tools: search, biography, season/career stats and game logs."""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from typing_extensions import NotRequired, TypedDict

from ..config import CacheTTL, Limits, MLBApi
from ..mlb import endpoints, get_client
from . import advanced
from .common import (
    JSON,
    HittingOrPitching,
    StatGroup,
    Stats,
    StatType,
    clamp,
    current_season,
    dig,
    season_cache_ttl,
    stat_blocks,
)

# Key stats kept per game in a game log (the API returns ~40 per game).
GAME_LOG_FIELDS: dict[str, tuple[str, ...]] = {
    "hitting": (
        "atBats", "runs", "hits", "doubles", "triples", "homeRuns", "rbi",
        "baseOnBalls", "strikeOuts", "stolenBases",
    ),
    "pitching": (
        "inningsPitched", "hits", "runs", "earnedRuns", "baseOnBalls", "strikeOuts",
        "homeRuns", "numberOfPitches", "wins", "losses", "saves",
    ),
}  # fmt: skip


# --------------------------------------------------------------- result types --


class PlayerMatch(TypedDict):
    player_id: int
    name: str | None
    position: str | None
    current_team: str | None
    active: bool | None
    mlb_debut: str | None


class PlayerSearch(TypedDict):
    """Players whose name matches the search."""

    count: int
    players: list[PlayerMatch]
    note: NotRequired[str]


class PlayerBio(TypedDict):
    player_id: int
    name: str | None
    current_team: str | None
    position: str | None
    jersey: str | None
    age: int | None
    birth_date: str | None
    birthplace: str
    height: str | None
    weight_lbs: int | None
    bats: str | None
    throws: str | None
    mlb_debut: str | None
    active: bool | None


class StatLine(TypedDict):
    """One season or career line. A player traded mid-season has one line per team."""

    season: str | None
    team: str | None
    league: str | None
    stats: Stats


class PlayerStats(TypedDict):
    player_id: int
    group: StatGroup
    stat_type: StatType
    splits: list[StatLine]
    season: NotRequired[int]
    advanced: NotRequired[Stats]  # single seasons of hitting or pitching only
    note: NotRequired[str]


class GameLogEntry(TypedDict):
    date: str | None
    opponent: str | None
    home_away: Literal["home", "away"]
    team_result: Literal["W", "L"]
    game_pk: int | None
    summary: str | None
    stats: Stats


class GameLog(TypedDict):
    """A player's games, most recent first."""

    player_id: int
    group: HittingOrPitching
    season: int
    games_played_in_season: int
    games: list[GameLogEntry]
    note: NotRequired[str]


# ----------------------------------------------------------------- formatting --


def _format_search_result(person: JSON) -> PlayerMatch:
    return {
        "player_id": person["id"],
        "name": person.get("fullName"),
        "position": dig(person, "primaryPosition", "abbreviation"),
        "current_team": dig(person, "currentTeam", "name"),
        "active": person.get("active"),
        "mlb_debut": person.get("mlbDebutDate"),
    }


def _format_bio(person: JSON) -> PlayerBio:
    birthplace_parts = (
        person.get("birthCity"),
        person.get("birthStateProvince"),
        person.get("birthCountry"),
    )
    return {
        "player_id": person["id"],
        "name": person.get("fullName"),
        "current_team": dig(person, "currentTeam", "name"),
        "position": dig(person, "primaryPosition", "name"),
        "jersey": person.get("primaryNumber"),
        "age": person.get("currentAge"),
        "birth_date": person.get("birthDate"),
        "birthplace": ", ".join(part for part in birthplace_parts if part),
        "height": person.get("height"),
        "weight_lbs": person.get("weight"),
        "bats": dig(person, "batSide", "description"),
        "throws": dig(person, "pitchHand", "description"),
        "mlb_debut": person.get("mlbDebutDate"),
        "active": person.get("active"),
    }


def _format_stat_split(split: JSON) -> StatLine:
    stats = split.get("stat") or {}
    return {
        "season": split.get("season"),
        "team": dig(split, "team", "name"),
        "league": dig(split, "league", "name"),
        "stats": {name: value for name, value in stats.items() if name != "summary"},
    }


def _format_game_log_entry(split: JSON, fields: tuple[str, ...]) -> GameLogEntry:
    stats = split.get("stat") or {}
    return {
        "date": split.get("date"),
        "opponent": dig(split, "opponent", "name"),
        "home_away": "home" if split.get("isHome") else "away",
        "team_result": "W" if split.get("isWin") else "L",
        "game_pk": dig(split, "game", "gamePk"),
        "summary": stats.get("summary"),
        "stats": {name: stats[name] for name in fields if name in stats},
    }


def _all_splits(stats_response: JSON) -> list[JSON]:
    return [split for block in stats_response.get("stats", []) for split in block.get("splits", [])]


def _game_order(split: JSON) -> tuple[str, int]:
    """Chronological sort key; game_number orders the two games of a doubleheader."""
    return split.get("date", ""), dig(split, "game", "gameNumber") or 1


# ---------------------------------------------------------------------- tools --


async def search_players(name: str, active_only: bool = False) -> PlayerSearch:
    """Find MLB players by name and return their player_id (needed by other player tools).

    Args:
        name: Full or partial name, e.g. "Ohtani" or "Aaron Judge".
        active_only: Only return currently active players.
    """
    search = await get_client().get(
        endpoints.PEOPLE_SEARCH,
        {
            "names": name,
            "sportIds": MLBApi.SPORT_ID_MLB,
            "active": "true" if active_only else None,
            "hydrate": "currentTeam",
        },
        ttl=CacheTTL.ROSTER,  # current teams change with trades and signings
    )
    people = search.get("people", [])[: Limits.MAX_SEARCH_RESULTS]
    if not people:
        return {"count": 0, "players": [], "note": f"No MLB players match '{name}'."}
    players = [_format_search_result(person) for person in people]
    return {"count": len(players), "players": players}


async def get_player_info(player_id: int) -> PlayerBio:
    """Get a player's biography: team, position, age, height, handedness, debut, birthplace.

    Args:
        player_id: MLB player id from search_players.
    """
    data = await get_client().get(
        endpoints.person(player_id), {"hydrate": "currentTeam"}, ttl=CacheTTL.ROSTER
    )
    people = data.get("people") or []
    if not people:
        raise ToolError(f"No player with id {player_id}")
    return _format_bio(people[0])


async def get_player_stats(
    player_id: int,
    group: StatGroup = "hitting",
    stat_type: StatType = "season",
    season: int | None = None,
) -> PlayerStats:
    """Get a player's batting, pitching or fielding stats. For one season of hitting or
    pitching it also returns advanced stats: WAR, wRC+, wOBA, FIP, xFIP, ERA-/FIP- and the
    Statcast expected stats xBA, xSLG and xwOBA (for pitchers, what hitters did against them).

    Args:
        player_id: MLB player id from search_players.
        group: "hitting", "pitching" or "fielding".
        stat_type: "season" (one season), "career" (career totals) or "yearByYear" (every season).
        season: Season year for stat_type="season"; defaults to the current one.
    """
    is_single_season = stat_type == "season"
    if is_single_season:
        season = season or current_season()
    # Advanced stats are separate stats types, fetched in the same request.
    with_advanced = is_single_season and group in advanced.FIELDS
    stat_types = (stat_type, *advanced.STAT_TYPES) if with_advanced else (stat_type,)

    data = await get_client().get(
        endpoints.person_stats(player_id),
        {
            "stats": ",".join(stat_types),
            "group": group,
            "season": season if is_single_season else None,
        },
        ttl=season_cache_ttl(season) if is_single_season else CacheTTL.CURRENT_SEASON,
    )
    blocks = stat_blocks(data)
    splits = [_format_stat_split(split) for split in blocks.get(stat_type, [])]

    result: PlayerStats = {
        "player_id": player_id,
        "group": group,
        "stat_type": stat_type,
        "splits": splits,
    }
    if is_single_season:
        result["season"] = season
    if with_advanced and (advanced_stats := advanced.pick_advanced(blocks, group)):
        result["advanced"] = advanced_stats
    if not splits:
        result["note"] = (
            f"No {group} stats found. The player may not have played in {season} "
            "or this stat group may not apply (e.g. pitching stats for a position player)."
            if is_single_season
            else f"No {group} stats found for this player."
        )
    return result


async def get_player_game_log(
    player_id: int,
    group: HittingOrPitching = "hitting",
    season: int | None = None,
    last_n: int = Limits.DEFAULT_GAME_LOG_GAMES,
) -> GameLog:
    """Get a player's game-by-game stats, most recent game first. Use for recent form, hot or
    cold streaks, and "how did he do last night / this week" questions.

    Args:
        player_id: MLB player id from search_players.
        group: "hitting" or "pitching".
        season: Season year; defaults to the current one.
        last_n: Number of most recent games to return (1-162).
    """
    season = season or current_season()
    data = await get_client().get(
        endpoints.person_stats(player_id),
        {"stats": "gameLog", "group": group, "season": season},
        ttl=season_cache_ttl(season),
    )
    games = sorted(_all_splits(data), key=_game_order, reverse=True)
    recent = games[: clamp(last_n, 1, Limits.MAX_GAME_LOG_GAMES)]

    result: GameLog = {
        "player_id": player_id,
        "group": group,
        "season": season,
        "games_played_in_season": len(games),
        "games": [_format_game_log_entry(split, GAME_LOG_FIELDS[group]) for split in recent],
    }
    if not games:
        result["note"] = f"No {group} game log for {season}."
    return result
