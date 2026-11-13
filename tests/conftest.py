"""Offline test fixtures: route all MLB API traffic to a fake handler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest

from mlb_stats_mcp.mlb import MLBClient, set_client

Handler = Callable[[httpx.Request], httpx.Response]
NO_RETRY_DELAY = 0.0  # keep retry tests instant


@dataclass
class FakeMLB:
    """A real MLBClient whose HTTP traffic goes to `handler` instead of the internet."""

    handler: Handler
    requests: list[httpx.Request] = field(default_factory=list)

    def __post_init__(self) -> None:
        def recording_handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.handler(request)

        self.client = MLBClient(
            transport=httpx.MockTransport(recording_handler),
            retry_base_delay=NO_RETRY_DELAY,
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake_mlb():
    """Factory: fake_mlb(handler) builds a FakeMLB and makes the tools use it."""

    def install(handler: Handler) -> FakeMLB:
        fake = FakeMLB(handler)
        set_client(fake.client)
        return fake

    yield install
    set_client(None)
