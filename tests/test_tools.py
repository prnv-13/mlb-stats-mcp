"""Tool-level tests through a real in-process MCP client, with MLB faked out."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp import Client

from mlb_stats_mcp import api
from mlb_stats_mcp.server import mcp

pytestmark = pytest.mark.anyio

TEAMS = {
    "teams": [
        {"id": 147, "name": "New York Yankees", "abbreviation": "NYY", "teamName": "Yankees"},
        {"id": 121, "name": "New York Mets", "abbreviation": "NYM", "teamName": "Mets"},
        {"id": 119, "name": "Los Angeles Dodgers", "abbreviation": "LAD", "teamName": "Dodgers"},
    ]
}


def _split(date: str, summary: str, game_number: int = 1) -> dict:
    return {
        "date": date,
        "isHome": True,
        "isWin": True,
        "opponent": {"name": "Boston Red Sox"},
        "game": {"gamePk": hash(date) % 10**6, "gameNumber": game_number},
        "stat": {"summary": summary, "atBats": 4, "hits": 2, "homeRuns": 1, "groundOuts": 9},
    }


async def call(name: str, args: dict) -> tuple[bool, str]:
    async with Client(mcp) as client:
        result = await client.call_tool(name, args)
        return result.is_error, result.content[0].text


async def test_game_log_returns_most_recent_games_first(mock_mlb):
    log = {
        "stats": [
            {
                "splits": [
                    _split("2026-04-01", "oldest"),
                    _split("2026-04-03", "doubleheader g1", game_number=1),
                    _split("2026-04-03", "doubleheader g2", game_number=2),
                    _split("2026-04-02", "middle"),
                ]
            }
        ]
    }
    requests = mock_mlb(lambda r: httpx.Response(200, json=log))
    is_error, text = await call(
        "get_player_game_log", {"player_id": 1, "season": 2026, "last_n": 3}
    )
    assert not is_error
    data = json.loads(text)
    assert [g["summary"] for g in data["games"]] == ["doubleheader g2", "doubleheader g1", "middle"]
    assert data["games_played_in_season"] == 4
    assert "groundOuts" not in data["games"][0]["stats"]  # trimmed to key stats
    assert requests[0].url.params["stats"] == "gameLog"


async def test_team_names_resolve_and_ambiguity_is_reported(mock_mlb):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/teams"):
            return httpx.Response(200, json=TEAMS)
        assert "/teams/119/roster" in request.url.path
        return httpx.Response(200, json={"roster": []})

    mock_mlb(handler)
    is_error, _ = await call("get_team_roster", {"team": "lad"})
    assert not is_error
    is_error, text = await call("get_team_roster", {"team": "New York"})
    assert is_error and "ambiguous" in text and "Mets" in text


async def test_finished_game_is_cached_longer_than_live_game(mock_mlb):
    def handler(state: str):
        def h(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/schedule"):
                games = [{"status": {"abstractGameState": state, "detailedState": state}}]
                return httpx.Response(200, json={"dates": [{"games": games}]})
            if request.url.path.endswith("/linescore"):
                return httpx.Response(200, json={"teams": {"away": {}, "home": {}}, "innings": []})
            team = {"team": {"name": "X"}, "players": {}, "batters": [], "pitchers": []}
            return httpx.Response(200, json={"teams": {"away": team, "home": team}})

        return h

    mock_mlb(handler("Final"))
    await call("get_game", {"game_pk": 1})
    final_expiry = max(api.cache.expires_at(k) for k in api.cache)

    mock_mlb(handler("Live"))
    api.cache.clear()
    is_error, text = await call("get_game", {"game_pk": 2})
    live_expiry = max(api.cache.expires_at(k) for k in api.cache)

    assert not is_error and json.loads(text)["status"] == "Live"
    assert final_expiry - live_expiry > api.TTL_DAY / 2
