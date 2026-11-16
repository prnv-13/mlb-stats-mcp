"""End-to-end check: connect to the server like a real MCP client and call every tool.

Usage:
    uv run scripts/smoke_test.py                           # launches the server over stdio
    uv run scripts/smoke_test.py http://localhost:8000/mcp # tests a running HTTP server
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Any

from mcp import Client, StdioServerParameters

# Known-good fixtures from the 2026 season.
SEASON = 2026
AARON_JUDGE_ID = 592450
YOSHINOBU_YAMAMOTO_ID = 808967
TARIK_SKUBAL_ID = 669373
SHOHEI_OHTANI_ID = 660271
DODGERS_GAME_DATE = f"{SEASON}-09-15"
DODGERS_AT_REDS_GAME_PK = 824466

PREVIEW_CHARS = 300
EXIT_OK, EXIT_FAILED = 0, 1


@dataclass
class Check:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    expect_error: bool = False


CHECKS = [
    Check("list_teams"),
    Check("search_players", {"name": "Aaron Judge"}),
    Check("get_player_info", {"player_id": AARON_JUDGE_ID}),
    Check("get_player_stats", {"player_id": AARON_JUDGE_ID, "season": SEASON}),
    Check("get_player_stats", {"player_id": AARON_JUDGE_ID, "stat_type": "career"}),
    Check("get_player_game_log", {"player_id": AARON_JUDGE_ID, "season": SEASON, "last_n": 5}),
    Check(
        "get_player_game_log",
        {"player_id": YOSHINOBU_YAMAMOTO_ID, "group": "pitching", "season": SEASON, "last_n": 3},
    ),
    Check("get_matchup", {"batter_id": AARON_JUDGE_ID, "pitcher_id": TARIK_SKUBAL_ID}),
    Check(
        "get_matchup",
        {"batter_id": AARON_JUDGE_ID, "pitcher_id": YOSHINOBU_YAMAMOTO_ID, "include_postseason": True},
    ),
    Check("compare_players", {"player_ids": [AARON_JUDGE_ID, SHOHEI_OHTANI_ID], "season": SEASON}),
    Check(
        "compare_players",
        {"player_ids": [AARON_JUDGE_ID, SHOHEI_OHTANI_ID], "stat_type": "career"},
    ),
    Check("get_league_leaders", {"category": "homeRuns", "season": SEASON, "limit": 3}),
    Check("get_league_leaders", {"category": "battingAverage", "season": SEASON, "limit": 3}),
    Check("get_league_leaders", {"category": "homeRuns", "team": "NYY", "season": SEASON}),
    Check(
        "get_league_leaders",
        {"category": "strikeouts", "group": "pitching", "season": SEASON, "league": "AL", "limit": 3},
    ),
    Check("get_standings", {"season": SEASON, "league": "AL"}),
    Check("get_team_roster", {"team": "Yankees"}),
    Check("get_schedule", {"date": DODGERS_GAME_DATE, "team": "LAD"}),
    Check("get_game", {"game_pk": DODGERS_AT_REDS_GAME_PK}),
    Check("get_transactions", {"team": "Yankees", "start_date": f"{SEASON}-10-01", "limit": 3}),
    Check("get_transactions", {"player_id": AARON_JUDGE_ID, "kind": "status_changes", "limit": 2}),
    Check("get_award_winners", {"award": "mvp", "season": SEASON}),
    Check("get_award_winners", {"award": "cy_young", "league": "NL", "seasons": 3}),
    Check("get_player_awards", {"player_id": AARON_JUDGE_ID}),
    Check("get_award_winners", {"award": "hall_of_fame", "season": SEASON}),
    Check("get_free_agents", {"limit": 5}),
    Check("get_free_agents", {"position": "SS", "status": "all", "limit": 5}),
    Check("get_draft", {"season": SEASON, "limit": 3}),
    Check("get_draft", {"season": SEASON, "team": "Yankees", "round": "1"}),
    Check(
        "get_player_stats",
        {"player_id": TARIK_SKUBAL_ID, "group": "pitching", "season": SEASON},
    ),
    Check(
        "get_player_stats",
        {"player_id": AARON_JUDGE_ID, "season": SEASON, "split": "handedness"},
    ),
    Check(
        "get_player_stats",
        {
            "player_id": TARIK_SKUBAL_ID,
            "group": "pitching",
            "stat_type": "career",
            "split": "month",
        },
    ),
    Check("get_team_roster", {"team": "Not A Team"}, expect_error=True),
    Check("get_transactions", {"start_date": "not-a-date"}, expect_error=True),
    Check("compare_players", {"player_ids": [AARON_JUDGE_ID]}, expect_error=True),
    Check(
        "get_player_stats",
        {"player_id": AARON_JUDGE_ID, "group": "fielding", "split": "home_away"},
        expect_error=True,
    ),
]


def _server_target() -> str | StdioServerParameters:
    if len(sys.argv) > 1:
        return sys.argv[1]  # URL of a running HTTP server
    return StdioServerParameters(command="uv", args=["run", "mlb-stats-mcp"])


async def main() -> int:
    failures = 0
    async with Client(_server_target()) as client:
        tools = await client.list_tools()
        print(f"server exposes {len(tools.tools)} tools: {[t.name for t in tools.tools]}\n")

        for check in CHECKS:
            result = await client.call_tool(check.tool, check.arguments)
            text = result.content[0].text if result.content else ""
            status = "ERROR" if result.is_error else "ok"
            if result.is_error != check.expect_error:
                failures += 1
                status += " (UNEXPECTED)"
            elif not result.is_error and result.structured_content != json.loads(text):
                # Real API data has a field the tool's result TypedDict doesn't declare.
                failures += 1
                status += " (structuredContent differs from text)"
            preview = text if len(text) < PREVIEW_CHARS else text[:PREVIEW_CHARS] + "..."
            print(f"[{status}] {check.tool}({json.dumps(check.arguments)})\n    {preview}\n")

    print("FAILED" if failures else "ALL PASSED")
    return EXIT_FAILED if failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
