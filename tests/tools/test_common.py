from __future__ import annotations

from mlb_stats_mcp.config import CacheTTL
from mlb_stats_mcp.tools.common import clamp, current_season, dig, season_cache_ttl


def test_dig_follows_nested_keys_and_tolerates_gaps():
    game = {"venue": {"name": "Fenway Park"}, "status": None}
    assert dig(game, "venue", "name") == "Fenway Park"
    assert dig(game, "status", "detailedState") is None
    assert dig(game, "missing", "deeper") is None


def test_clamp():
    assert clamp(0, 1, 50) == 1
    assert clamp(99, 1, 50) == 50
    assert clamp(10, 1, 50) == 10


def test_past_seasons_are_cached_longer_than_the_current_one():
    assert season_cache_ttl(current_season() - 1) == CacheTTL.STATIC
    assert season_cache_ttl(current_season()) == CacheTTL.CURRENT_SEASON
    assert season_cache_ttl(None) == CacheTTL.CURRENT_SEASON
