from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.anyio

YANKEES_ID = 147


def _board(group: str, leader: str) -> dict:
    return {
        "leaderCategory": "battingAverage",
        "statGroup": group,
        "leaders": [{"rank": 1, "person": {"id": 1, "fullName": leader}, "value": ".300"}],
    }


# Without a group, MLB returns a board per group, pitching first.
BOARDS = [_board("pitching", "A Pitcher"), _board("hitting", "A Hitter"), _board("catching", "C")]


def _api(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/teams"):
        teams = [{"id": YANKEES_ID, "name": "New York Yankees", "abbreviation": "NYY"}]
        return httpx.Response(200, json={"teams": teams})
    return httpx.Response(200, json={"leagueLeaders": BOARDS})


@pytest.mark.parametrize(
    ("arguments", "leader"),
    [
        ({"category": "battingAverage"}, "A Hitter"),
        ({"category": "strikeouts"}, "A Pitcher"),
        ({"category": "battingAverage", "group": "pitching"}, "A Pitcher"),
    ],
)
async def test_picks_the_board_for_the_group(fake_mlb, call_tool, arguments, leader):
    fake_mlb(_api)
    result = await call_tool("get_league_leaders", {"season": 2026, **arguments})
    assert result.data["leaders"][0]["name"] == leader


async def test_team_leaders(fake_mlb, call_tool):
    fake = fake_mlb(_api)
    result = await call_tool(
        "get_league_leaders", {"category": "battingAverage", "team": "NYY", "league": "NL"}
    )
    assert result.data["team"] == "New York Yankees"
    params = fake.requests[-1].url.params
    assert params["teamId"] == str(YANKEES_ID)
    assert "leagueId" not in params  # a team already implies its league
