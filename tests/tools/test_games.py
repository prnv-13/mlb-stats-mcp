from __future__ import annotations

import time

import httpx
import pytest

from mlb_stats_mcp.config import CacheTTL

pytestmark = pytest.mark.anyio

EMPTY_TEAM_BOX = {"team": {"name": "X"}, "players": {}, "batters": [], "pitchers": []}


def _game_api(abstract_state: str):
    """A fake MLB API serving one game in the given state."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/schedule"):
            status = {"abstractGameState": abstract_state, "detailedState": abstract_state}
            return httpx.Response(200, json={"dates": [{"games": [{"status": status}]}]})
        if path.endswith("/linescore"):
            return httpx.Response(200, json={"teams": {"away": {}, "home": {}}, "innings": []})
        return httpx.Response(200, json={"teams": {"away": EMPTY_TEAM_BOX, "home": EMPTY_TEAM_BOX}})

    return handler


def _longest_cache_lifetime(fake) -> float:
    cache = fake.client.cache
    return max(cache.expires_at(key) for key in cache) - time.monotonic()


async def test_finished_game_is_cached_for_a_day(fake_mlb, call_tool):
    fake = fake_mlb(_game_api("Final"))
    result = await call_tool("get_game", {"game_pk": 1})
    assert result.data["status"] == "Final"
    assert _longest_cache_lifetime(fake) > CacheTTL.STATIC - CacheTTL.LIVE_GAME


async def test_live_game_is_cached_for_seconds(fake_mlb, call_tool):
    fake = fake_mlb(_game_api("Live"))
    result = await call_tool("get_game", {"game_pk": 1})
    assert result.data["status"] == "Live"
    assert _longest_cache_lifetime(fake) <= CacheTTL.LIVE_GAME
