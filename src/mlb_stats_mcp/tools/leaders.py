"""League leaders tool."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError
from typing_extensions import TypedDict

from ..config import League, Limits, MLBApi
from ..mlb import endpoints, get_client
from .common import JSON, LeagueCode, StatGroup, clamp, current_season, dig, season_cache_ttl


class Leader(TypedDict):
    rank: int | None
    player_id: int | None
    name: str | None
    team: str | None
    value: str | None  # formatted by MLB, e.g. "58" or ".331"


class LeaderBoard(TypedDict):
    """The top players in one stat category, best first. Tied players share a rank."""

    category: str | None
    group: str | None
    season: int
    league: LeagueCode
    leaders: list[Leader]


def _format_leader(entry: JSON) -> Leader:
    return {
        "rank": entry.get("rank"),
        "player_id": dig(entry, "person", "id"),
        "name": dig(entry, "person", "fullName"),
        "team": dig(entry, "team", "name"),
        "value": entry.get("value"),
    }


def _league_filter(league: LeagueCode) -> int | None:
    """The leaders endpoint takes one league id, or none for both leagues."""
    league_ids = League.IDS_BY_CODE[league]
    return league_ids[0] if len(league_ids) == 1 else None


async def get_league_leaders(
    category: str = "homeRuns",
    season: int | None = None,
    group: StatGroup | None = None,
    league: LeagueCode = "MLB",
    limit: int = Limits.DEFAULT_LEADERS,
) -> LeaderBoard:
    """Get the league leaders for a statistic.

    Args:
        category: Stat category, e.g. homeRuns, battingAverage, runsBattedIn, stolenBases,
            onBasePlusSlugging, hits, earnedRunAverage, strikeouts, wins, saves, walksAndHitsPerInningPitched.
        season: Season year; defaults to the current one.
        group: "hitting" or "pitching". Needed for categories shared by both (e.g. strikeouts
            for pitchers vs. batters). Defaults to the API's choice.
        league: "AL", "NL" or "MLB" (both leagues).
        limit: How many leaders to return (1-50).
    """
    season = season or current_season()
    data = await get_client().get(
        endpoints.STATS_LEADERS,
        {
            "leaderCategories": category,
            "season": season,
            "statGroup": group,
            "leagueId": _league_filter(league),
            "sportId": MLBApi.SPORT_ID_MLB,
            "limit": clamp(limit, 1, Limits.MAX_LEADERS),
        },
        ttl=season_cache_ttl(season),
    )
    categories = data.get("leagueLeaders", [])
    if not categories:
        raise ToolError(f"Unknown leader category '{category}' or no data for {season}.")

    board = categories[0]
    return {
        "category": board.get("leaderCategory"),
        "group": board.get("statGroup"),
        "season": season,
        "league": league,
        "leaders": [_format_leader(entry) for entry in board.get("leaders", [])],
    }
