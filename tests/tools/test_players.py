from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.anyio


def _game_log_split(date: str, summary: str, game_number: int = 1) -> dict:
    return {
        "date": date,
        "isHome": True,
        "isWin": True,
        "opponent": {"name": "Boston Red Sox"},
        "game": {"gamePk": 1, "gameNumber": game_number},
        "stat": {"summary": summary, "atBats": 4, "hits": 2, "homeRuns": 1, "groundOuts": 9},
    }


async def test_game_log_returns_most_recent_games_first(fake_mlb, call_tool):
    log = {
        "stats": [
            {
                "splits": [
                    _game_log_split("2026-04-01", "oldest"),
                    _game_log_split("2026-04-03", "doubleheader g1", game_number=1),
                    _game_log_split("2026-04-03", "doubleheader g2", game_number=2),
                    _game_log_split("2026-04-02", "middle"),
                ]
            }
        ]
    }
    fake = fake_mlb(lambda r: httpx.Response(200, json=log))

    result = await call_tool("get_player_game_log", {"player_id": 1, "season": 2026, "last_n": 3})

    assert not result.is_error
    games = result.data["games"]
    assert [g["summary"] for g in games] == ["doubleheader g2", "doubleheader g1", "middle"]
    assert result.data["games_played_in_season"] == 4
    assert "groundOuts" not in games[0]["stats"]  # trimmed to key stats
    assert fake.requests[0].url.params["stats"] == "gameLog"


async def test_unknown_player_is_reported_to_the_model(fake_mlb, call_tool):
    fake_mlb(lambda r: httpx.Response(200, json={"people": []}))
    result = await call_tool("get_player_info", {"player_id": 999})
    assert result.is_error and "No player with id 999" in result.text
