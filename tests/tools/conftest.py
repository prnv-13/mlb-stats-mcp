"""Call tools the way a real client does: through an in-process MCP connection.

Every successful call is also checked for agreement between its two copies of the
result: the JSON text the model reads and the structuredContent programs read. The SDK
builds structuredContent by validating against the tool's result TypedDict, which
silently drops keys the TypedDict doesn't declare, so a mismatch means a type is stale.
"""

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
        assert len(result.content) == 1, "a tool result should be a single text block"
        tool_result = ToolResult(result.is_error, result.content[0].text)
        if not result.is_error:
            assert result.structured_content == tool_result.data, (
                f"{name}'s structuredContent differs from its text; update its result TypedDict"
            )
        return tool_result

    return call
