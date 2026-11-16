from __future__ import annotations

import pytest
from mcp import Client

from mlb_stats_mcp.server import build_server
from mlb_stats_mcp.tools import ALL_TOOLS

pytestmark = pytest.mark.anyio


async def test_every_tool_declares_the_fields_it_returns():
    async with Client(build_server()) as client:
        tools = (await client.list_tools()).tools

    assert len(tools) == len(ALL_TOOLS)
    for tool in tools:
        schema = tool.output_schema
        assert schema and schema["type"] == "object", tool.name
        assert schema.get("properties"), f"{tool.name} returns an untyped dict"
        assert "result" not in schema["properties"], f"{tool.name} returns a bare list"
