from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.anyio

TEAMS = {
    "teams": [
        {
            "id": 147,
            "name": "New York Yankees",
            "abbreviation": "NYY",
            "teamName": "Yankees",
            "league": {"name": "American League"},
            "division": {"name": "American League East"},
            "venue": {"name": "Yankee Stadium"},
        },
        {"id": 121, "name": "New York Mets", "abbreviation": "NYM", "teamName": "Mets"},
        {"id": 119, "name": "Los Angeles Dodgers", "abbreviation": "LAD", "teamName": "Dodgers"},
    ]
}
DODGERS_ID = 119


def _teams_or_roster(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/teams"):
        return httpx.Response(200, json=TEAMS)
    return httpx.Response(200, json={"roster": []})


async def test_list_teams_returns_a_count_and_teams_sorted_by_name(fake_mlb, call_tool):
    fake_mlb(_teams_or_roster)
    result = await call_tool("list_teams", {})

    assert result.data["count"] == len(TEAMS["teams"])
    teams = result.data["teams"]
    assert [t["abbreviation"] for t in teams] == ["LAD", "NYM", "NYY"]
    assert teams[-1] == {
        "id": 147,
        "name": "New York Yankees",
        "abbreviation": "NYY",
        "league": "American League",
        "division": "American League East",
        "venue": "Yankee Stadium",
    }


@pytest.mark.parametrize("team", ["lad", "Dodgers", "Los Angeles Dodgers", str(DODGERS_ID), "angeles"])
async def test_team_resolves_from_any_common_name(fake_mlb, call_tool, team):
    fake = fake_mlb(_teams_or_roster)
    result = await call_tool("get_team_roster", {"team": team})
    assert not result.is_error
    assert fake.requests[-1].url.path.endswith(f"/teams/{DODGERS_ID}/roster")


async def test_ambiguous_team_lists_the_options(fake_mlb, call_tool):
    fake_mlb(_teams_or_roster)
    result = await call_tool("get_team_roster", {"team": "New York"})
    assert result.is_error and "ambiguous" in result.text and "Mets" in result.text


async def test_unknown_team_points_to_list_teams(fake_mlb, call_tool):
    fake_mlb(_teams_or_roster)
    result = await call_tool("get_team_roster", {"team": "Not A Team"})
    assert result.is_error and "list_teams" in result.text
