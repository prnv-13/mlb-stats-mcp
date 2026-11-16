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


def _search_api(request: httpx.Request) -> httpx.Response:
    judge = {"id": 592450, "fullName": "Aaron Judge", "active": True}
    if request.url.params.get("hydrate") == "currentTeam":
        judge["currentTeam"] = {"name": "New York Yankees"}
    found = [judge] if request.url.params["names"] == "judge" else []
    return httpx.Response(200, json={"people": found})


async def test_search_returns_matches_with_their_current_team(fake_mlb, call_tool):
    fake = fake_mlb(_search_api)
    result = await call_tool("search_players", {"name": "judge"})
    assert result.data["count"] == 1
    assert result.data["players"][0]["current_team"] == "New York Yankees"
    assert "note" not in result.data
    assert len(fake.requests) == 1  # the team comes hydrated with the search


async def test_search_without_matches_says_so(fake_mlb, call_tool):
    fake_mlb(_search_api)
    result = await call_tool("search_players", {"name": "nobody"})
    assert result.data == {"count": 0, "players": [], "note": "No MLB players match 'nobody'."}


def _block(stat_type: str, splits: list[dict]) -> dict:
    return {"type": {"displayName": stat_type}, "splits": splits}


async def test_season_stats_include_advanced_stats(fake_mlb, call_tool):
    response = {
        "stats": [
            _block("season", [{"season": "2026", "stat": {"homeRuns": 40, "summary": "..."}}]),
            _block("sabermetrics", [{"stat": {"war": 8.123456, "wRcPlus": 180.4, "spd": 3.1}}]),
            _block("expectedStatistics", [{"stat": {"avg": ".300", "slg": ".650"}}]),
        ]
    }
    fake = fake_mlb(lambda r: httpx.Response(200, json=response))
    result = await call_tool("get_player_stats", {"player_id": 1, "season": 2026})

    assert [s["stats"] for s in result.data["splits"]] == [{"homeRuns": 40}]
    advanced = {"war": 8.123, "wRcPlus": 180.4, "xba": ".300", "xslg": ".650"}
    assert result.data["advanced"] == advanced
    assert "pitch_mix" not in result.data  # pitchers only
    params = fake.requests[0].url.params
    assert params["stats"] == "season,sabermetrics,expectedStatistics"
    assert "metrics" not in params


@pytest.mark.parametrize(
    ("arguments", "requested"),
    [({"stat_type": "career"}, "career"), ({"group": "fielding", "season": 2026}, "season")],
)
async def test_advanced_stats_are_only_for_seasons_of_hitting_or_pitching(
    fake_mlb, call_tool, arguments, requested
):
    fake = fake_mlb(lambda r: httpx.Response(200, json={"stats": []}))
    result = await call_tool("get_player_stats", {"player_id": 1, **arguments})
    assert "advanced" not in result.data
    assert fake.requests[0].url.params["stats"] == requested


def _arsenal_row(code: str, description: str, share: float, speed: float) -> dict:
    stat = {"type": {"code": code, "description": description}, "percentage": share}
    return {"stat": {**stat, "count": round(share * 1000), "averageSpeed": speed}}


def _metric_row(code: str, metric: str, value: float) -> dict:
    event = {"details": {"type": {"code": code}}}
    return {"stat": {"metric": {"name": metric, "averageValue": value}, "event": event}}


async def test_pitching_season_includes_pitch_mix_most_used_first(fake_mlb, call_tool):
    response = {
        "stats": [
            _block("season", [{"season": "2026", "stat": {"era": "2.50"}}]),
            _block(
                "pitchArsenal",
                [
                    _arsenal_row("CU", "Curveball", 0.0501, 80.44),
                    _arsenal_row("FF", "Four-seam FB", 0.3803, 96.789),
                ],
            ),
            _block(
                "metricAverages",
                [
                    _metric_row("FF", "releaseSpinRate", 2332.4),
                    _metric_row("FF", "releaseSpeed", 96.8),  # not spin: ignored
                ],
            ),
        ]
    }
    fake = fake_mlb(lambda r: httpx.Response(200, json=response))
    result = await call_tool(
        "get_player_stats", {"player_id": 1, "group": "pitching", "season": 2026}
    )

    assert result.data["pitch_mix"] == [
        {
            "pitch": "Four-seam FB",
            "code": "FF",
            "usage_pct": 38.0,
            "count": 380,
            "avg_speed_mph": 96.8,
            "avg_spin_rpm": 2332,
        },
        {
            "pitch": "Curveball",
            "code": "CU",
            "usage_pct": 5.0,
            "count": 50,
            "avg_speed_mph": 80.4,
            "avg_spin_rpm": None,  # no spin reported for this pitch
        },
    ]
    params = fake.requests[0].url.params
    assert params["stats"] == "season,sabermetrics,expectedStatistics,pitchArsenal,metricAverages"
    assert params["metrics"] == "releaseSpinRate"  # MLB fails without it


def _situation_row(code: str, team: str | None = None, **stats) -> dict:
    row = {"season": "2026", "split": {"code": code}, "stat": stats}
    if team:
        row["team"] = {"name": team}
    return row


async def test_split_returns_one_line_per_situation_in_order(fake_mlb, call_tool):
    rows = [
        _situation_row("vr", "Detroit Tigers", ops=".839"),
        _situation_row("vl", "Detroit Tigers", ops=".700"),
        _situation_row("vl", "Los Angeles Dodgers", ops=".800"),
        _situation_row("vl", ops=".750"),  # combined line for a player traded mid-season
    ]
    fake = fake_mlb(lambda r: httpx.Response(200, json={"stats": [_block("statSplits", rows)]}))
    result = await call_tool(
        "get_player_stats", {"player_id": 1, "season": 2026, "split": "handedness"}
    )

    data = result.data
    assert [(line["situation"], line["stats"]["ops"]) for line in data["splits"]] == [
        ("vs_left", ".750"),
        ("vs_right", ".839"),
    ]
    assert data["split"] == "handedness"
    assert "advanced" not in data and "pitch_mix" not in data
    params = fake.requests[0].url.params
    assert params["stats"] == "statSplits" and params["sitCodes"] == "vl,vr"
    assert params["season"] == "2026"


async def test_career_split_covers_every_season(fake_mlb, call_tool):
    fake = fake_mlb(lambda r: httpx.Response(200, json={"stats": []}))
    result = await call_tool(
        "get_player_stats", {"player_id": 1, "stat_type": "career", "split": "month"}
    )
    params = fake.requests[0].url.params
    assert params["stats"] == "careerStatSplits" and "season" not in params
    assert params["sitCodes"] == "3,4,5,6,7,8,9,10"
    assert result.data["note"] == "No hitting month splits found for this player."


@pytest.mark.parametrize("arguments", [{"group": "fielding"}, {"stat_type": "yearByYear"}])
async def test_split_needs_hitting_or_pitching_by_season_or_career(fake_mlb, call_tool, arguments):
    fake = fake_mlb(lambda r: httpx.Response(200, json={"stats": []}))
    result = await call_tool(
        "get_player_stats", {"player_id": 1, "split": "home_away", **arguments}
    )
    assert result.is_error and "split works for" in result.text
    assert not fake.requests


async def test_unknown_player_is_reported_to_the_model(fake_mlb, call_tool):
    fake_mlb(lambda r: httpx.Response(200, json={"people": []}))
    result = await call_tool("get_player_info", {"player_id": 999})
    assert result.is_error and "No player with id 999" in result.text
