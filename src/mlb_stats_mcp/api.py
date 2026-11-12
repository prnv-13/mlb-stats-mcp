"""Thin async client for the public MLB Stats API (statsapi.mlb.com).

Adds two things on top of plain HTTP:
- an in-memory TTL cache (see cache.py), so repeated questions don't re-hit MLB;
- retries with exponential backoff for transient failures (timeouts, 429, 5xx).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .cache import TTLCache

BASE_URL = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "mlb-stats-mcp/0.1"

# Cache lifetimes in seconds. Tools pick one based on how fast the data changes.
TTL_LIVE = 15  # in-progress games
TTL_SHORT = 60  # today's schedule
TTL_MEDIUM = 5 * 60  # standings, leaders, current-season stats
TTL_LONG = 60 * 60  # rosters, finished games
TTL_DAY = 24 * 60 * 60  # teams, bios, past seasons

MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.5  # seconds; doubles each retry
RETRY_STATUSES = {429, 500, 502, 503, 504}


class MLBApiError(ToolError):
    pass


cache = TTLCache()
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
    return _client


def _retry_delay(attempt: int, resp: httpx.Response | None) -> float:
    """Honor Retry-After if MLB sends one, otherwise exponential backoff with jitter."""
    if resp is not None:
        retry_after = resp.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), 10.0)
    return RETRY_BASE_DELAY * (2**attempt) * random.uniform(0.8, 1.2)


async def _fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        resp: httpx.Response | None = None
        try:
            resp = await _get_client().get(path, params=params)
        except httpx.TransportError as exc:  # timeouts, DNS, connection resets
            if last:
                raise MLBApiError(f"Could not reach MLB Stats API: {exc}") from exc
        else:
            if resp.status_code < 400:
                return resp.json()
            if resp.status_code == 404:
                raise MLBApiError(f"Not found: {path}")
            if resp.status_code not in RETRY_STATUSES or last:
                raise MLBApiError(f"MLB Stats API returned HTTP {resp.status_code} for {path}")
        await asyncio.sleep(_retry_delay(attempt, resp))
    raise AssertionError("unreachable")


async def get(path: str, ttl: float = TTL_MEDIUM, **params: Any) -> dict[str, Any]:
    """GET a Stats API path (dropping None params), served from cache when fresh.

    Errors are never cached, so a failed call is retried on the next request.
    """
    clean = {k: v for k, v in params.items() if v is not None}
    key = (path, tuple(sorted((k, str(v)) for k, v in clean.items())))
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = await _fetch(path, clean)
    cache.set(key, data, ttl)
    return data
