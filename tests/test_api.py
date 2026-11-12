"""Tests for the cached, retrying HTTP client (no network needed)."""

from __future__ import annotations

import httpx
import pytest

from mlb_stats_mcp import api
from mlb_stats_mcp.api import MLBApiError

pytestmark = pytest.mark.anyio


# ----------------------------------------------------------------- api.get --


async def test_repeat_request_is_served_from_cache(mock_mlb):
    requests = mock_mlb(lambda r: httpx.Response(200, json={"n": 1}))
    assert await api.get("/teams", sportId=1) == {"n": 1}
    assert await api.get("/teams", sportId=1) == {"n": 1}
    assert len(requests) == 1
    assert api.cache.hits == 1


async def test_different_params_are_cached_separately(mock_mlb):
    requests = mock_mlb(lambda r: httpx.Response(200, json={"q": r.url.params.get("season")}))
    assert await api.get("/standings", season=2025) == {"q": "2025"}
    assert await api.get("/standings", season=2026) == {"q": "2026"}
    assert len(requests) == 2


async def test_none_params_are_dropped(mock_mlb):
    requests = mock_mlb(lambda r: httpx.Response(200, json={}))
    await api.get("/schedule", sportId=1, teamId=None)
    assert "teamId" not in requests[0].url.params


async def test_retries_transient_errors_then_succeeds(mock_mlb):
    responses = iter([httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"ok": 1})])
    requests = mock_mlb(lambda r: next(responses))
    assert await api.get("/teams") == {"ok": 1}
    assert len(requests) == 3


async def test_retries_network_errors(mock_mlb):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("slow", request=request)
        return httpx.Response(200, json={"ok": 1})

    mock_mlb(handler)
    assert await api.get("/teams") == {"ok": 1}


async def test_gives_up_after_max_attempts(mock_mlb):
    requests = mock_mlb(lambda r: httpx.Response(503))
    with pytest.raises(MLBApiError, match="HTTP 503"):
        await api.get("/teams")
    assert len(requests) == api.MAX_ATTEMPTS


async def test_404_is_not_retried(mock_mlb):
    requests = mock_mlb(lambda r: httpx.Response(404))
    with pytest.raises(MLBApiError, match="Not found"):
        await api.get("/people/1")
    assert len(requests) == 1


async def test_errors_are_not_cached(mock_mlb):
    responses = iter([httpx.Response(400), httpx.Response(200, json={"ok": 1})])
    mock_mlb(lambda r: next(responses))
    with pytest.raises(MLBApiError):
        await api.get("/teams")
    assert await api.get("/teams") == {"ok": 1}


def test_retry_after_header_is_honored():
    resp = httpx.Response(429, headers={"Retry-After": "3"})
    assert api._retry_delay(0, resp) == 3.0
    assert api._retry_delay(0, httpx.Response(429, headers={"Retry-After": "999"})) == 10.0
