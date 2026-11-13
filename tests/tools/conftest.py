"""Call tools the way a real client does: through an in-process MCP connection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from mcp import Client

from mlb_stats_mcp.server import build_server


@dataclass
class ToolResult:
    is_error: bool
    text: str

    @property
    def data(self) -> Any:
        return json.loads(self.text)


@pytest.fixture
def call_tool():
    server = build_server()

    async def call(name: str, arguments: dict[str, Any]) -> ToolResult:
        async with Client(server) as client:
            result = await client.call_tool(name, arguments)
            return ToolResult(result.is_error, result.content[0].text)

    return call
