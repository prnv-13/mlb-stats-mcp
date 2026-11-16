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
        if request.url.path.endswith("/schedule"):
            game = {
                "status": {"abstractGameState": abstract_state, "detailedState": abstract_state},
                "linescore": {
                    "currentInningOrdinal": "9th",
                    "teams": {"away": {"runs": 2}, "home": {"runs": 5}},
                    "innings": [{"num": 1, "away": {"runs": 0}, "home": {"runs": 3}}],
                },
            }
            return httpx.Response(200, json={"dates": [{"games": [game]}]})
        return httpx.Response(200, json={"teams": {"away": EMPTY_TEAM_BOX, "home": EMPTY_TEAM_BOX}})

    return handler


def _longest_cache_lifetime(fake) -> float:
    cache = fake.client.cache
    return max(cache.expires_at(key) for key in cache) - time.monotonic()


async def test_game_combines_line_score_and_box_score_in_two_requests(fake_mlb, call_tool):
    fake = fake_mlb(_game_api("Final"))
    result = await call_tool("get_game", {"game_pk": 1})

    assert result.data["totals"]["home"]["runs"] == 5
    assert result.data["innings"] == [{"inning": 1, "away": 0, "home": 3}]
    assert [r.url.path.rsplit("/", 1)[-1] for r in fake.requests] == ["schedule", "boxscore"]
    assert fake.requests[0].url.params["hydrate"] == "linescore"


async def test_unknown_game_points_to_get_schedule(fake_mlb, call_tool):
    fake_mlb(lambda r: httpx.Response(200, json={"dates": []}))
    result = await call_tool("get_game", {"game_pk": 1})
    assert result.is_error and "get_schedule" in result.text


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
