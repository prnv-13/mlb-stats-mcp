"""Helpers and types shared by the tool modules."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from ..config import CacheTTL, MLBApi

JSON = dict[str, Any]

# Argument types. Literal values become enums in the JSON Schema the model sees.
StatGroup = Literal["hitting", "pitching", "fielding"]
HittingOrPitching = Literal["hitting", "pitching"]
SeasonOrCareer = Literal["season", "career"]
StatType = Literal["season", "career", "yearByYear"]
RosterType = Literal["active", "40Man", "fullSeason"]
LeagueCode = Literal["AL", "NL", "MLB"]
# These two mirror the keys of config.Transactions.TYPE_CODES_BY_KIND and
# config.Awards.IDS_BY_NAME (a test keeps them in sync).
TransactionKind = Literal[
    "all", "signings", "trades", "free_agency", "waivers_and_dfa", "releases",
    "status_changes", "call_ups_and_options",
]
AwardName = Literal[
    "mvp", "cy_young", "rookie_of_the_year", "manager_of_the_year", "comeback_player",
    "hank_aaron", "silver_slugger", "gold_glove", "platinum_glove", "all_star", "lcs_mvp",
    "world_series_mvp", "all_star_game_mvp", "roberto_clemente", "all_mlb_first_team",
    "all_mlb_second_team",
]  # fmt: skip

# Every tool only reads public data, so clients may call them freely.
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)

ISO_DATE_FORMAT = "%Y-%m-%d"


def today_date() -> date:
    """Today's date in MLB's timezone."""
    return datetime.now(MLBApi.TIMEZONE).date()


def today() -> str:
    """Today's date in MLB's timezone, as YYYY-MM-DD."""
    return today_date().strftime(ISO_DATE_FORMAT)


def parse_date(value: str, argument: str) -> date:
    """Parse a YYYY-MM-DD tool argument, telling the model which argument was wrong."""
    try:
        return datetime.strptime(value, ISO_DATE_FORMAT).date()
    except ValueError:
        raise ToolError(f"{argument} must be a date in YYYY-MM-DD format, got '{value}'.") from None


def current_season() -> int:
    return datetime.now(MLBApi.TIMEZONE).year


def season_cache_ttl(season: int | None) -> int:
    """Past seasons are final, so cache them for a day; the current one changes daily."""
    if season is not None and season < current_season():
        return CacheTTL.STATIC
    return CacheTTL.CURRENT_SEASON


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def dig(data: Any, *keys: str) -> Any:
    """Follow nested keys, returning None if any level is missing.

    dig(game, "venue", "name") replaces (game.get("venue") or {}).get("name").
    """
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data
