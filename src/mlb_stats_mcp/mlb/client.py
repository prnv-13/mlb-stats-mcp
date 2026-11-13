"""Async client for the MLB Stats API, with caching and retries."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Hashable, Mapping
from typing import Any

import httpx

from ..config import MLBApi, Retry
from .cache import TTLCache
from .errors import MLBApiError

JSON = dict[str, Any]
QueryParams = Mapping[str, Any]


def compute_retry_delay(
    attempt: int,
    response: httpx.Response | None,
    base_delay: float = Retry.BASE_DELAY_SECONDS,
) -> float:
    """Seconds to wait before retrying after failed attempt number `attempt` (0-based).

    Honors a numeric Retry-After header (capped); otherwise exponential backoff with jitter.
    """
    if response is not None:
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), Retry.MAX_RETRY_AFTER_SECONDS)
    backoff = base_delay * Retry.BACKOFF_MULTIPLIER**attempt
    return backoff * random.uniform(Retry.JITTER_MIN, Retry.JITTER_MAX)


class MLBClient:
    """Fetches JSON from the MLB Stats API.

    - Responses are cached per (path, params) for the TTL the caller passes.
    - Timeouts, connection errors, 429 and 5xx are retried with backoff.
    - Failures raise MLBApiError and are never cached.
    """

    def __init__(
        self,
        *,
        cache: TTLCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_base_delay: float = Retry.BASE_DELAY_SECONDS,
    ):
        self.cache = cache if cache is not None else TTLCache()
        self._retry_base_delay = retry_base_delay
        self._http = httpx.AsyncClient(
            base_url=MLBApi.BASE_URL,
            timeout=httpx.Timeout(MLBApi.TIMEOUT_SECONDS),
            headers={"User-Agent": MLBApi.USER_AGENT, "Accept": "application/json"},
            transport=transport,
        )

    async def get(self, path: str, params: QueryParams | None = None, *, ttl: float) -> JSON:
        """GET `path`, serving a cached copy if one is younger than `ttl` seconds.

        Params whose value is None are left out of the request.
        """
        query = {name: value for name, value in (params or {}).items() if value is not None}
        key = self._cache_key(path, query)

        cached = self.cache.get(key)
        if cached is not None:
            return cached

        data = await self._fetch_with_retries(path, query)
        self.cache.set(key, data, ttl)
        return data

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _cache_key(path: str, query: Mapping[str, Any]) -> Hashable:
        return path, tuple(sorted((name, str(value)) for name, value in query.items()))

    async def _fetch_with_retries(self, path: str, query: Mapping[str, Any]) -> JSON:
        for attempt in range(Retry.MAX_ATTEMPTS):
            is_last_attempt = attempt == Retry.MAX_ATTEMPTS - 1
            response: httpx.Response | None = None
            try:
                response = await self._http.get(path, params=query)
            except httpx.TransportError as exc:  # timeouts, DNS failures, connection resets
                if is_last_attempt:
                    raise MLBApiError(f"Could not reach MLB Stats API: {exc}") from exc
            else:
                if response.is_success:
                    return response.json()
                if response.status_code == httpx.codes.NOT_FOUND:
                    raise MLBApiError(f"Not found: {path}")
                if response.status_code not in Retry.RETRYABLE_STATUS_CODES or is_last_attempt:
                    raise MLBApiError(
                        f"MLB Stats API returned HTTP {response.status_code} for {path}"
                    )
            await asyncio.sleep(compute_retry_delay(attempt, response, self._retry_base_delay))

        raise AssertionError("unreachable: the last attempt always returns or raises")


_default_client: MLBClient | None = None


def get_client() -> MLBClient:
    """The process-wide client the tools use (created on first use)."""
    global _default_client
    if _default_client is None:
        _default_client = MLBClient()
    return _default_client


def set_client(client: MLBClient | None) -> None:
    """Replace the process-wide client, e.g. with one using a fake transport in tests."""
    global _default_client
    _default_client = client
