"""End-to-end check: connect to the server like a real MCP client and call every tool.

Usage:
    uv run scripts/smoke_test.py                           # launches the server over stdio
    uv run scripts/smoke_test.py http://localhost:8000/mcp # tests a running HTTP server
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import Client, StdioServerParameters

SEASON = 2026
CALLS: list[tuple[str, dict]] = [
    ("list_teams", {}),
    ("search_players", {"name": "Aaron Judge"}),
    ("get_player_info", {"player_id": 592450}),
    ("get_player_stats", {"player_id": 592450, "season": SEASON}),
    ("get_player_stats", {"player_id": 592450, "stat_type": "career"}),
    ("get_player_game_log", {"player_id": 592450, "season": SEASON, "last_n": 5}),
    ("get_player_game_log", {"player_id": 808967, "group": "pitching", "season": SEASON, "last_n": 3}),
    ("get_league_leaders", {"category": "homeRuns", "season": SEASON, "limit": 3}),
    ("get_league_leaders", {"category": "strikeouts", "group": "pitching", "season": SEASON, "league": "AL", "limit": 3}),
    ("get_standings", {"season": SEASON, "league": "AL"}),
    ("get_team_roster", {"team": "Yankees"}),
    ("get_schedule", {"date": f"{SEASON}-09-15", "team": "LAD"}),
    ("get_game", {"game_pk": 824466}),
    ("get_team_roster", {"team": "Not A Team"}),  # expected error
]


async def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else StdioServerParameters(
        command="uv", args=["run", "mlb-stats-mcp"]
    )
    failures = 0
    async with Client(target) as client:
        tools = await client.list_tools()
        print(f"server exposes {len(tools.tools)} tools: {[t.name for t in tools.tools]}\n")
        for name, args in CALLS:
            result = await client.call_tool(name, args)
            text = result.content[0].text if result.content else ""
            status = "ERROR" if result.is_error else "ok"
            expected_error = name == "get_team_roster" and args["team"] == "Not A Team"
            if result.is_error != expected_error:
                failures += 1
                status += " (UNEXPECTED)"
            preview = text if len(text) < 300 else text[:300] + "..."
            print(f"[{status}] {name}({json.dumps(args)})\n    {preview}\n")
    print("FAILED" if failures else "ALL PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
