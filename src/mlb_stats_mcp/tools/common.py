"""Helpers and types shared by the tool modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from mcp_types import ToolAnnotations

from ..config import CacheTTL, MLBApi

JSON = dict[str, Any]

# Argument types. Literal values become enums in the JSON Schema the model sees.
StatGroup = Literal["hitting", "pitching", "fielding"]
GameLogGroup = Literal["hitting", "pitching"]
StatType = Literal["season", "career", "yearByYear"]
RosterType = Literal["active", "40Man", "fullSeason"]
LeagueCode = Literal["AL", "NL", "MLB"]

# Every tool only reads public data, so clients may call them freely.
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True, idempotentHint=True)

ISO_DATE_FORMAT = "%Y-%m-%d"


def today() -> str:
    """Today's date in MLB's timezone, as YYYY-MM-DD."""
    return datetime.now(MLBApi.TIMEZONE).strftime(ISO_DATE_FORMAT)


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
