"""Leaders tool: the top players in a stat across MLB, one league or one team."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError
from typing_extensions import TypedDict

from ..config import League, Limits, MLBApi
from ..mlb import endpoints, get_client
from .common import JSON, LeagueCode, StatGroup, clamp, current_season, dig, season_cache_ttl
from .teams import resolve_team

# Without a group argument, MLB returns one board per group that has the category
# (battingAverage: hitting, pitching and catching), in no useful order. Pick hitting,
# except where the usual meaning is the pitchers' board.
DEFAULT_GROUP = "hitting"
PITCHING_FIRST_CATEGORIES = frozenset({"strikeouts"})


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
    team: str | None
    leaders: list[Leader]


def _format_leader(entry: JSON) -> Leader:
    return {
        "rank": entry.get("rank"),
        "player_id": dig(entry, "person", "id"),
        "name": dig(entry, "person", "fullName"),
        "team": dig(entry, "team", "name"),
        "value": entry.get("value"),
    }


def _pick_board(boards: list[JSON], category: str, group: StatGroup | None) -> JSON:
    if group is None:
        group = "pitching" if category in PITCHING_FIRST_CATEGORIES else DEFAULT_GROUP
    return next((board for board in boards if board.get("statGroup") == group), boards[0])


def _league_filter(league: LeagueCode) -> int | None:
    """The leaders endpoint takes one league id, or none for both leagues."""
    league_ids = League.IDS_BY_CODE[league]
    return league_ids[0] if len(league_ids) == 1 else None


async def get_league_leaders(
    category: str = "homeRuns",
    season: int | None = None,
    group: StatGroup | None = None,
    league: LeagueCode = "MLB",
    team: str | None = None,
    limit: int = Limits.DEFAULT_LEADERS,
) -> LeaderBoard:
    """Get the leaders in a statistic across MLB, one league, or one team (e.g. "Yankees home
    run leaders").

    Args:
        category: Stat category, e.g. homeRuns, battingAverage, runsBattedIn, stolenBases,
            onBasePlusSlugging, hits, earnedRunAverage, strikeouts, wins, saves,
            walksAndHitsPerInningPitched.
        season: Season year; defaults to the current one.
        group: "hitting" or "pitching", for categories both share. Defaults to hitting,
            except strikeouts, which defaults to pitching.
        league: "AL", "NL" or "MLB" (both leagues). Ignored when team is given.
        team: Only this team's players (name, abbreviation or id).
        limit: How many leaders to return (1-50). Tied players share a rank, so a few more
            may come back.
    """
    season = season or current_season()
    resolved_team = await resolve_team(team) if team else None
    data = await get_client().get(
        endpoints.STATS_LEADERS,
        {
            "leaderCategories": category,
            "season": season,
            "statGroup": group,
            "leagueId": None if resolved_team else _league_filter(league),
            "teamId": resolved_team["id"] if resolved_team else None,
            "sportId": MLBApi.SPORT_ID_MLB,
            "limit": clamp(limit, 1, Limits.MAX_LEADERS),
        },
        ttl=season_cache_ttl(season),
    )
    boards = data.get("leagueLeaders", [])
    if not boards:
        raise ToolError(f"Unknown leader category '{category}' or no data for {season}.")

    board = _pick_board(boards, category, group)
    return {
        "category": board.get("leaderCategory"),
        "group": board.get("statGroup"),
        "season": season,
        "league": league,
        "team": resolved_team["name"] if resolved_team else None,
        "leaders": [_format_leader(entry) for entry in board.get("leaders", [])],
    }
