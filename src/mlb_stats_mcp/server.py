"""Builds the MCP server: identity, instructions for the model, and tools."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .config import Server
from .tools import register_tools

INSTRUCTIONS = (
    "Live and historical Major League Baseball data from the public MLB Stats API. "
    "Use search_players to turn a name into a player_id before calling player tools. "
    "get_matchup gives a batter's history against one pitcher, and compare_players puts "
    "2-5 players side by side. "
    "Team arguments accept a name, nickname, abbreviation or numeric id "
    "(e.g. 'Yankees', 'NYY', 'New York Yankees', '147'). "
    "Seasons default to the current year; during the off-season pass the previous year "
    "if the current one has no data. In the off-season, get_free_agents ranks who is still "
    "available (or who signed where), get_transactions covers signings and trades, and "
    "get_award_winners covers MVP, Cy Young, other awards and the Hall of Fame. For a single "
    "season, get_player_stats and compare_players include WAR, wRC+, FIP and expected stats, "
    "and get_player_stats adds a pitcher's pitch mix. For situational questions (vs lefties, "
    "home or away, with runners in scoring position) pass get_player_stats a split. "
    "Dates are YYYY-MM-DD."
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
