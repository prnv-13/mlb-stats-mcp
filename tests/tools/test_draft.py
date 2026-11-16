from __future__ import annotations

import httpx
import pytest

from mlb_stats_mcp.tools.common import current_season

pytestmark = pytest.mark.anyio

SEASON = current_season()
YANKEES_ID = 147


def _pick(number: int, name: str, *, bonus: str | None = "1000000", passed: bool = False) -> dict:
    return {
        "pickNumber": number,
        "pickRound": "1",
        "roundPickNumber": number,
        "isDrafted": not passed,
        "isPass": passed,
        "signingBonus": bonus,
        "pickValue": "2000000",
        "team": {"name": "New York Yankees"},
        "person": {"id": number, "fullName": name, "primaryPosition": {"abbreviation": "SS"}},
        "school": {"name": "UCLA", "schoolClass": "4YR JR"},
    }


def _api(drafts: dict[int, list[dict]]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/teams"):
            teams = [{"id": YANKEES_ID, "name": "New York Yankees", "abbreviation": "NYY"}]
            return httpx.Response(200, json={"teams": teams})
        season = int(request.url.path.rsplit("/", 1)[-1])
        picks = drafts.get(season, [])
        rounds = [{"round": "1", "picks": picks}] if picks else []
        return httpx.Response(200, json={"drafts": {"draftYear": season, "rounds": rounds}})

    return handler


async def test_picks_in_order_without_passed_picks(fake_mlb, call_tool):
    picks = [_pick(2, "Second", bonus=None), _pick(1, "First"), _pick(3, "Passed", passed=True)]
    fake_mlb(_api({SEASON: picks}))
    result = await call_tool("get_draft", {})

    rows = result.data["picks"]
    assert [row["name"] for row in rows] == ["First", "Second"]
    assert (rows[0]["signing_bonus"], rows[0]["slot_value"]) == (1_000_000, 2_000_000)
    assert rows[1]["signing_bonus"] is None  # not signed yet
    assert result.data["total_picks"] == 2


async def test_defaults_to_last_years_draft_before_this_years(fake_mlb, call_tool):
    fake = fake_mlb(_api({SEASON - 1: [_pick(1, "Last Year")]}))
    result = await call_tool("get_draft", {})
    assert result.data["season"] == SEASON - 1
    assert [r.url.path.rsplit("/", 1)[-1] for r in fake.requests] == [str(SEASON), str(SEASON - 1)]


async def test_an_explicit_season_is_not_replaced(fake_mlb, call_tool):
    fake_mlb(_api({}))
    result = await call_tool("get_draft", {"season": SEASON})
    assert result.data["season"] == SEASON and "No" in result.data["note"]


async def test_round_and_team_filters_go_to_the_api(fake_mlb, call_tool):
    fake = fake_mlb(_api({SEASON: [_pick(1, "First")]}))
    result = await call_tool("get_draft", {"round": "CB-A", "team": "Yankees"})
    params = fake.requests[-1].url.params
    assert (params["round"], params["teamId"]) == ("CB-A", str(YANKEES_ID))
    assert result.data["team"] == "New York Yankees"


async def test_limit_is_explained(fake_mlb, call_tool):
    fake_mlb(_api({SEASON: [_pick(n, f"P{n}") for n in range(1, 4)]}))
    result = await call_tool("get_draft", {"limit": 2})
    assert len(result.data["picks"]) == 2 and "raise limit" in result.data["note"]
