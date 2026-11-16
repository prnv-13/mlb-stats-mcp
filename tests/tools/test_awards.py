from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.anyio


def _recipient(award_id: str, season: int, player_id: int, name: str) -> dict:
    return {
        "id": award_id,
        "season": str(season),
        "player": {
            "id": player_id,
            "nameFirstLast": name,
            "primaryPosition": {"abbreviation": "RF"},
        },
        "team": {"id": 147, "name": "New York Yankees"},
    }


RECIPIENTS = {
    "ALMVP": [
        _recipient("ALMVP", 2025, 1, "AL 2025"),
        _recipient("ALMVP", 2024, 2, "AL 2024"),
        _recipient("ALMVP", 2023, 3, "AL 2023"),
    ],
    "NLMVP": [
        _recipient("NLMVP", 2025, 11, "NL 2025"),
        _recipient("NLMVP", 2024, 12, "NL 2024"),
    ],
    # Comeback Player lists its winner once per voting body.
    "ALCPOY": [
        _recipient("ALCPOY", 2025, 7, "Comeback"),
        _recipient("ALCPOY", 2025, 7, "Comeback"),
    ],
    "WSMVP": [_recipient("WSMVP", 2025, 21, "WS 2025")],
    "MLBHOF": [
        _recipient("MLBHOF", 2025, 31, "Inductee A"),
        _recipient("MLBHOF", 2025, 32, "Inductee B"),
    ],
}


def _serve_awards(request: httpx.Request) -> httpx.Response:
    award_id = request.url.path.split("/awards/")[1].split("/")[0]
    return httpx.Response(200, json={"awards": RECIPIENTS.get(award_id, [])})


async def test_defaults_to_latest_season_in_both_leagues(fake_mlb, call_tool):
    fake_mlb(_serve_awards)
    result = await call_tool("get_award_winners", {"award": "mvp"})
    assert [(w["season"], w["league"], w["name"]) for w in result.data["winners"]] == [
        (2025, "AL", "AL 2025"),
        (2025, "NL", "NL 2025"),
    ]


async def test_one_league_fetches_only_that_award(fake_mlb, call_tool):
    fake = fake_mlb(_serve_awards)
    result = await call_tool("get_award_winners", {"award": "mvp", "league": "AL", "seasons": 2})
    assert [w["season"] for w in result.data["winners"]] == [2025, 2024]
    assert [r.url.path for r in fake.requests] == ["/api/v1/awards/ALMVP/recipients"]


async def test_season_window_counts_back_from_season(fake_mlb, call_tool):
    fake_mlb(_serve_awards)
    result = await call_tool(
        "get_award_winners", {"award": "mvp", "league": "AL", "season": 2024, "seasons": 2}
    )
    assert [w["season"] for w in result.data["winners"]] == [2024, 2023]


async def test_mlb_wide_award_ignores_league(fake_mlb, call_tool):
    fake_mlb(_serve_awards)
    result = await call_tool("get_award_winners", {"award": "world_series_mvp", "league": "AL"})
    assert result.data["leagues"] == ["MLB"]
    assert result.data["winners"][0]["name"] == "WS 2025"


async def test_hall_of_fame_lists_every_inductee_of_a_year(fake_mlb, call_tool):
    fake_mlb(_serve_awards)
    result = await call_tool("get_award_winners", {"award": "hall_of_fame"})
    assert [w["name"] for w in result.data["winners"]] == ["Inductee A", "Inductee B"]
    assert result.data["leagues"] == ["MLB"]


async def test_duplicate_listings_are_merged(fake_mlb, call_tool):
    fake_mlb(_serve_awards)
    result = await call_tool("get_award_winners", {"award": "comeback_player", "league": "AL"})
    assert len(result.data["winners"]) == 1


async def test_season_without_winners_explains_why(fake_mlb, call_tool):
    fake_mlb(_serve_awards)
    result = await call_tool("get_award_winners", {"award": "mvp", "season": 2026})
    assert result.data["winners"] == []
    assert "announced in November" in result.data["note"]


async def test_player_awards_keep_major_awards_only(fake_mlb, call_tool):
    person = {
        "id": 592450,
        "fullName": "Aaron Judge",
        "awards": [
            {"id": "ALMVP", "season": "2024"},
            {"id": "ALMVP", "season": "2022"},
            {"id": "ALROY", "season": "2017"},
            {"id": "ALPOW", "season": "2024"},  # AL Player of the Week: not in the catalog
            {"id": "SALMSAS", "season": "2014"},  # a minor-league honor
        ],
    }
    fake_mlb(lambda r: httpx.Response(200, json={"people": [person]}))
    result = await call_tool("get_player_awards", {"player_id": 592450})
    assert result.data["awards"] == [
        {"award": "mvp", "league": "AL", "count": 2, "seasons": [2022, 2024]},
        {"award": "rookie_of_the_year", "league": "AL", "count": 1, "seasons": [2017]},
    ]
