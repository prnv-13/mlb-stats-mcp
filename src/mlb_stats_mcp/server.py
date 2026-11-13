"""Builds the MCP server: identity, instructions for the model, and tools."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .config import Server
from .tools import register_tools

INSTRUCTIONS = (
    "Live and historical Major League Baseball data from the public MLB Stats API. "
    "Use search_players to turn a name into a player_id before calling player tools. "
    "Team arguments accept a name, nickname, abbreviation or numeric id "
    "(e.g. 'Yankees', 'NYY', 'New York Yankees', '147'). "
    "Seasons default to the current year; during the off-season pass the previous year "
    "if the current one has no data. Dates are YYYY-MM-DD."
)


def build_server() -> MCPServer:
    server = MCPServer(
        name=Server.NAME,
        title=Server.TITLE,
        version=Server.VERSION,
        instructions=INSTRUCTIONS,
    )
    register_tools(server)
    return server
