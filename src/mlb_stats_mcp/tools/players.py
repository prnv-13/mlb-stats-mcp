"""Player tools: search, biography, season/career stats and game logs."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

from ..config import CacheTTL, Limits, MLBApi
from ..mlb import endpoints, get_client
from .common import (
    JSON,
    GameLogGroup,
    StatGroup,
    StatType,
    clamp,
    current_season,
    dig,
    season_cache_ttl,
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


# ----------------------------------------------------------------- formatting --


def _format_search_result(person: JSON, current_team: str | None) -> JSON:
    return {
        "player_id": person["id"],
        "name": person.get("fullName"),
        "position": dig(person, "primaryPosition", "abbreviation"),
        "current_team": current_team,
        "active": person.get("active"),
        "mlb_debut": person.get("mlbDebutDate"),
    }


def _format_bio(person: JSON) -> JSON:
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


def _format_stat_split(split: JSON) -> JSON:
    stats = split.get("stat") or {}
    return {
        "season": split.get("season"),
        "team": dig(split, "team", "name"),
        "league": dig(split, "league", "name"),
        "stats": {name: value for name, value in stats.items() if name != "summary"},
    }


def _format_game_log_entry(split: JSON, fields: tuple[str, ...]) -> JSON:
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


async def search_players(name: str, active_only: bool = False) -> list[JSON]:
    """Find MLB players by name and return their player_id (needed by other player tools).

    Args:
        name: Full or partial name, e.g. "Ohtani" or "Aaron Judge".
        active_only: Only return currently active players.
    """
    client = get_client()
    search = await client.get(
        endpoints.PEOPLE_SEARCH,
        {
            "names": name,
            "sportIds": MLBApi.SPORT_ID_MLB,
            "active": "true" if active_only else None,
        },
        ttl=CacheTTL.STATIC,
    )
    people = search.get("people", [])[: Limits.MAX_SEARCH_RESULTS]
    if not people:
        return []

    # Search results omit the current team, so fetch it for all matches in one request.
    details = await client.get(
        endpoints.PEOPLE,
        {"personIds": ",".join(str(p["id"]) for p in people), "hydrate": "currentTeam"},
        ttl=CacheTTL.ROSTER,
    )
    team_by_player = {p["id"]: dig(p, "currentTeam", "name") for p in details.get("people", [])}
    return [_format_search_result(p, team_by_player.get(p["id"])) for p in people]


async def get_player_info(player_id: int) -> JSON:
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
) -> JSON:
    """Get a player's batting, pitching or fielding stats.

    Args:
        player_id: MLB player id from search_players.
        group: "hitting", "pitching" or "fielding".
        stat_type: "season" (one season), "career" (career totals) or "yearByYear" (every season).
        season: Season year for stat_type="season"; defaults to the current one.
    """
    is_single_season = stat_type == "season"
    if is_single_season:
        season = season or current_season()

    data = await get_client().get(
        endpoints.person_stats(player_id),
        {"stats": stat_type, "group": group, "season": season if is_single_season else None},
        ttl=season_cache_ttl(season) if is_single_season else CacheTTL.CURRENT_SEASON,
    )
    splits = [_format_stat_split(split) for split in _all_splits(data)]

    result: JSON = {"player_id": player_id, "group": group, "stat_type": stat_type, "splits": splits}
    if is_single_season:
        result["season"] = season
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
    group: GameLogGroup = "hitting",
    season: int | None = None,
    last_n: int = Limits.DEFAULT_GAME_LOG_GAMES,
) -> JSON:
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

    result: JSON = {
        "player_id": player_id,
        "group": group,
        "season": season,
        "games_played_in_season": len(games),
        "games": [_format_game_log_entry(split, GAME_LOG_FIELDS[group]) for split in recent],
    }
    if not games:
        result["note"] = f"No {group} game log for {season}."
    return result
