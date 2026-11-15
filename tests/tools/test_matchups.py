from __future__ import annotations

import httpx
import pytest

from mlb_stats_mcp.config import Limits, Matchups

pytestmark = pytest.mark.anyio

JUDGE, SKUBAL, OHTANI = 592450, 669373, 660271
PEOPLE = {
    JUDGE: {"id": JUDGE, "fullName": "Aaron Judge"},
    SKUBAL: {"id": SKUBAL, "fullName": "Tarik Skubal"},
    OHTANI: {"id": OHTANI, "fullName": "Shohei Ohtani"},
}


def _people_response(request: httpx.Request, stats_by_id: dict | None = None) -> httpx.Response:
    ids = [int(pid) for pid in request.url.params["personIds"].split(",")]
    people = []
    for pid in ids:
        if pid in PEOPLE:
            person = dict(PEOPLE[pid])
            if stats_by_id and pid in stats_by_id:
                person["stats"] = [{"splits": stats_by_id[pid]}]
            people.append(person)
    return httpx.Response(200, json={"people": people})


# ------------------------------------------------------------------ matchups --


def _vs_split(plate_appearances: int, season: str | None = None, game_type: str = "R") -> dict:
    split = {
        "gameType": game_type,
        "stat": {"plateAppearances": plate_appearances, "ops": "1.000", "groundOuts": 3},
    }
    if season:
        split["season"] = season
    return split


def _matchup_api(totals: list[dict], seasons: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stats"):
            blocks = [
                {"type": {"displayName": "vsPlayerTotal"}, "splits": totals},
                {"type": {"displayName": "vsPlayer"}, "splits": seasons},
            ]
            return httpx.Response(200, json={"stats": blocks})
        return _people_response(request)

    return handler


async def test_matchup_reports_totals_and_seasons_newest_first(fake_mlb, call_tool):
    big_sample = Matchups.MIN_MEANINGFUL_PLATE_APPEARANCES
    fake = fake_mlb(
        _matchup_api([_vs_split(big_sample)], [_vs_split(20, "2023"), _vs_split(30, "2025")])
    )
    result = await call_tool("get_matchup", {"batter_id": JUDGE, "pitcher_id": SKUBAL})

    data = result.data
    assert data["batter"]["name"] == "Aaron Judge" and data["pitcher"]["name"] == "Tarik Skubal"
    assert data["career_totals"]["regular_season"]["plateAppearances"] == big_sample
    assert "groundOuts" not in data["career_totals"]["regular_season"]  # trimmed to key stats
    assert [row["season"] for row in data["by_season"]] == ["2025", "2023"]
    assert "note" not in data

    stats_request = fake.requests[-1]
    assert stats_request.url.params["opposingPlayerId"] == str(SKUBAL)
    assert stats_request.url.params["gameType"] == "R"


async def test_small_samples_are_flagged(fake_mlb, call_tool):
    fake_mlb(_matchup_api([_vs_split(5)], [_vs_split(5, "2025")]))
    result = await call_tool("get_matchup", {"batter_id": JUDGE, "pitcher_id": SKUBAL})
    assert "Small sample" in result.data["note"]


async def test_never_faced(fake_mlb, call_tool):
    fake_mlb(_matchup_api([], []))
    result = await call_tool("get_matchup", {"batter_id": JUDGE, "pitcher_id": SKUBAL})
    assert result.data["career_totals"] == {}
    assert "never faced" in result.data["note"]


async def test_postseason_rounds_are_requested_and_labeled(fake_mlb, call_tool):
    fake = fake_mlb(_matchup_api([_vs_split(60), _vs_split(3, game_type="W")], []))
    result = await call_tool(
        "get_matchup", {"batter_id": JUDGE, "pitcher_id": SKUBAL, "include_postseason": True}
    )
    assert set(result.data["career_totals"]) == {"regular_season", "world_series"}
    assert fake.requests[-1].url.params["gameType"] == "R,F,D,L,W"


async def test_unknown_player_id_is_rejected(fake_mlb, call_tool):
    fake_mlb(_matchup_api([], []))
    result = await call_tool("get_matchup", {"batter_id": JUDGE, "pitcher_id": 1})
    assert result.is_error and "No player with id 1" in result.text


# ---------------------------------------------------------------- comparison --


def _season_split(team: str | None, **stats) -> dict:
    split = {"stat": stats}
    if team:
        split["team"] = {"name": team}
    else:
        split["numTeams"] = 2
    return split


async def test_compare_names_the_leader_of_each_stat(fake_mlb, call_tool):
    stats = {
        JUDGE: [_season_split("New York Yankees", ops=".950", homeRuns=40, strikeOuts=150)],
        OHTANI: [_season_split("Los Angeles Dodgers", ops=".950", homeRuns=45, strikeOuts=160)],
    }
    fake_mlb(lambda r: _people_response(r, stats))
    result = await call_tool("compare_players", {"player_ids": [JUDGE, OHTANI], "season": 2026})

    assert result.data["leaders"] == {
        "ops": "tie",
        "homeRuns": "Shohei Ohtani",
        "strikeOuts": "Aaron Judge",  # fewer is better
    }


async def test_lower_is_better_for_pitching_rate_stats(fake_mlb, call_tool):
    stats = {
        JUDGE: [_season_split("A", era="2.50", whip="1.10", strikeOuts=150)],
        SKUBAL: [_season_split("B", era="3.10", whip="0.95", strikeOuts=200)],
    }
    fake_mlb(lambda r: _people_response(r, stats))
    result = await call_tool(
        "compare_players", {"player_ids": [JUDGE, SKUBAL], "group": "pitching", "season": 2026}
    )
    assert result.data["leaders"] == {
        "era": "Aaron Judge",
        "whip": "Tarik Skubal",
        "strikeOuts": "Tarik Skubal",
    }


async def test_traded_player_uses_combined_line_and_lists_teams(fake_mlb, call_tool):
    stats = {
        SKUBAL: [
            _season_split(None, homeRuns=30),
            _season_split("Detroit Tigers", homeRuns=10),
            _season_split("Los Angeles Dodgers", homeRuns=20),
        ],
        JUDGE: [_season_split("New York Yankees", homeRuns=25)],
    }
    fake_mlb(lambda r: _people_response(r, stats))
    result = await call_tool("compare_players", {"player_ids": [SKUBAL, JUDGE], "season": 2026})

    traded = result.data["players"][0]
    assert traded["stats"]["homeRuns"] == 30
    assert traded["played_for"] == ["Detroit Tigers", "Los Angeles Dodgers"]
    assert result.data["leaders"]["homeRuns"] == "Tarik Skubal"


async def test_player_without_stats_is_noted_not_ranked(fake_mlb, call_tool):
    stats = {JUDGE: [_season_split("New York Yankees", homeRuns=25)]}
    fake_mlb(lambda r: _people_response(r, stats))
    result = await call_tool("compare_players", {"player_ids": [JUDGE, SKUBAL], "season": 2026})
    assert result.data["leaders"] == {}
    assert "Tarik Skubal" in result.data["note"]


@pytest.mark.parametrize("player_ids", [[JUDGE], [JUDGE, JUDGE], list(range(1, 7))])
async def test_needs_two_to_five_different_players(fake_mlb, call_tool, player_ids):
    fake = fake_mlb(lambda r: _people_response(r))
    result = await call_tool("compare_players", {"player_ids": player_ids})
    assert result.is_error and str(Limits.MAX_COMPARE_PLAYERS) in result.text
    assert not fake.requests


async def test_career_comparison_skips_the_season_filter(fake_mlb, call_tool):
    fake = fake_mlb(lambda r: _people_response(r))
    await call_tool("compare_players", {"player_ids": [JUDGE, OHTANI], "stat_type": "career"})
    hydrate = fake.requests[0].url.params["hydrate"]
    assert "type=[career]" in hydrate and "season=" not in hydrate
