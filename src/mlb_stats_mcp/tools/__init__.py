"""MCP tools, one module per area. ALL_TOOLS is the order clients see them in."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import (
    awards,
    draft,
    free_agents,
    games,
    leaders,
    matchups,
    players,
    standings,
    teams,
    transactions,
)
from .common import READ_ONLY

ALL_TOOLS = (
    teams.list_teams,
    teams.get_team_roster,
    players.search_players,
    players.get_player_info,
    players.get_player_stats,
    players.get_player_game_log,
    matchups.get_matchup,
    matchups.compare_players,
    leaders.get_league_leaders,
    games.get_schedule,
    games.get_game,
    standings.get_standings,
    transactions.get_transactions,
    free_agents.get_free_agents,
    awards.get_award_winners,
    awards.get_player_awards,
    draft.get_draft,
)


def register_tools(server: MCPServer) -> None:
    for tool in ALL_TOOLS:
        server.add_tool(tool, annotations=READ_ONLY)
