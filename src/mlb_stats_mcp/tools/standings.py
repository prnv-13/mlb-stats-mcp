"""Standings tool."""

from __future__ import annotations

from ..config import League
from ..mlb import endpoints, get_client
from .common import JSON, LeagueCode, current_season, dig, season_cache_ttl


def _format_team_record(record: JSON) -> JSON:
    return {
        "rank": record.get("divisionRank"),
        "team": dig(record, "team", "name"),
        "wins": record.get("wins"),
        "losses": record.get("losses"),
        "pct": record.get("winningPercentage"),
        "games_back": record.get("gamesBack"),
        "wild_card_games_back": record.get("wildCardGamesBack"),
        "streak": dig(record, "streak", "streakCode"),
        "run_differential": record.get("runDifferential"),
    }


def _format_division(division: JSON) -> JSON:
    return {
        "division": dig(division, "division", "name"),
        "teams": [_format_team_record(r) for r in division.get("teamRecords", [])],
    }


async def get_standings(season: int | None = None, league: LeagueCode = "MLB") -> JSON:
    """Get division standings: wins, losses, win %, games back, streak and run differential.

    Args:
        season: Season year; defaults to the current one.
        league: "AL", "NL" or "MLB" (both).
    """
    season = season or current_season()
    league_ids = ",".join(str(league_id) for league_id in League.IDS_BY_CODE[league])
    data = await get_client().get(
        endpoints.STANDINGS,
        {"leagueId": league_ids, "season": season, "hydrate": "division,team"},
        ttl=season_cache_ttl(season),
    )
    return {
        "season": season,
        "divisions": [_format_division(d) for d in data.get("records", [])],
    }
