"""Offline test fixtures: route all MLB API traffic to a fake handler."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from mlb_stats_mcp import api

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def mock_mlb(monkeypatch: pytest.MonkeyPatch):
    """Install a fake MLB API. Call it with a handler; it returns the list of requests made."""
    api.cache.clear()
    monkeypatch.setattr(api, "RETRY_BASE_DELAY", 0.0)
    requests: list[httpx.Request] = []

    def install(handler: Handler) -> list[httpx.Request]:
        def recording(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handler(request)

        monkeypatch.setattr(
            api,
            "_client",
            httpx.AsyncClient(base_url=api.BASE_URL, transport=httpx.MockTransport(recording)),
        )
        return requests

    yield install
    api.cache.clear()
