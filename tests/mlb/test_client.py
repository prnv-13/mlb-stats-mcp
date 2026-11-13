"""Tests for MLBClient caching and retries (no network needed)."""

from __future__ import annotations

import httpx
import pytest

from mlb_stats_mcp.config import CacheTTL, Retry
from mlb_stats_mcp.mlb import MLBApiError, compute_retry_delay

pytestmark = pytest.mark.anyio

TTL = CacheTTL.CURRENT_SEASON


# --------------------------------------------------------------------- caching --


async def test_repeat_request_is_served_from_cache(fake_mlb):
    fake = fake_mlb(lambda r: httpx.Response(200, json={"n": 1}))
    assert await fake.client.get("/teams", {"sportId": 1}, ttl=TTL) == {"n": 1}
    assert await fake.client.get("/teams", {"sportId": 1}, ttl=TTL) == {"n": 1}
    assert len(fake.requests) == 1
    assert fake.client.cache.hits == 1


async def test_different_params_are_cached_separately(fake_mlb):
    fake = fake_mlb(lambda r: httpx.Response(200, json={"q": r.url.params.get("season")}))
    assert await fake.client.get("/standings", {"season": 2025}, ttl=TTL) == {"q": "2025"}
    assert await fake.client.get("/standings", {"season": 2026}, ttl=TTL) == {"q": "2026"}
    assert len(fake.requests) == 2


async def test_none_params_are_dropped(fake_mlb):
    fake = fake_mlb(lambda r: httpx.Response(200, json={}))
    await fake.client.get("/schedule", {"sportId": 1, "teamId": None}, ttl=TTL)
    assert "teamId" not in fake.requests[0].url.params


async def test_errors_are_not_cached(fake_mlb):
    responses = iter([httpx.Response(400), httpx.Response(200, json={"ok": 1})])
    fake = fake_mlb(lambda r: next(responses))
    with pytest.raises(MLBApiError):
        await fake.client.get("/teams", ttl=TTL)
    assert await fake.client.get("/teams", ttl=TTL) == {"ok": 1}


# --------------------------------------------------------------------- retries --


async def test_retries_transient_errors_then_succeeds(fake_mlb):
    responses = iter(
        [httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"ok": 1})]
    )
    fake = fake_mlb(lambda r: next(responses))
    assert await fake.client.get("/teams", ttl=TTL) == {"ok": 1}
    assert len(fake.requests) == 3


async def test_retries_network_errors(fake_mlb):
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ConnectTimeout("slow", request=request)
        return httpx.Response(200, json={"ok": 1})

    fake = fake_mlb(handler)
    assert await fake.client.get("/teams", ttl=TTL) == {"ok": 1}


async def test_gives_up_after_max_attempts(fake_mlb):
    fake = fake_mlb(lambda r: httpx.Response(503))
    with pytest.raises(MLBApiError, match="HTTP 503"):
        await fake.client.get("/teams", ttl=TTL)
    assert len(fake.requests) == Retry.MAX_ATTEMPTS


async def test_404_is_not_retried(fake_mlb):
    fake = fake_mlb(lambda r: httpx.Response(404))
    with pytest.raises(MLBApiError, match="Not found"):
        await fake.client.get("/people/1", ttl=TTL)
    assert len(fake.requests) == 1


def test_retry_after_header_is_honored_and_capped():
    assert compute_retry_delay(0, httpx.Response(429, headers={"Retry-After": "3"})) == 3.0
    huge_wait = httpx.Response(429, headers={"Retry-After": "999"})
    assert compute_retry_delay(0, huge_wait) == Retry.MAX_RETRY_AFTER_SECONDS


def test_backoff_grows_exponentially_within_jitter():
    base = Retry.BASE_DELAY_SECONDS
    for attempt in range(Retry.MAX_ATTEMPTS):
        expected = base * Retry.BACKOFF_MULTIPLIER**attempt
        delay = compute_retry_delay(attempt, None)
        assert expected * Retry.JITTER_MIN <= delay <= expected * Retry.JITTER_MAX
