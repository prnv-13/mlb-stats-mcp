from __future__ import annotations

import httpx
import pytest

from mlb_stats_mcp.config import FreeAgency
from mlb_stats_mcp.tools.common import current_season

pytestmark = pytest.mark.anyio

YANKEES, METS = 147, 121
SEASON = current_season()


def _entry(
    player_id: int,
    name: str,
    position: tuple[str, str],
    *,
    new_team: int | None = None,
    notes: str | None = None,
) -> dict:
    abbreviation, position_type = position
    entry = {
        "player": {"id": player_id, "fullName": name},
        "originalTeam": {"id": YANKEES, "name": "New York Yankees"},
        # MLB always sends newTeam; it has no id until a team signs or claims the player.
        "newTeam": {"id": new_team, "name": "New York Mets"} if new_team else {"link": "/x"},
        "position": {"abbreviation": abbreviation, "type": position_type},
        "dateDeclared": f"{SEASON}-11-02",
    }
    if notes:
        entry["notes"] = notes
    return entry


SHORTSTOP, PITCHER = ("SS", "Infielder"), ("SP", "Pitcher")
CLASS = [
    _entry(1, "Low War", SHORTSTOP),
    _entry(2, "High War", PITCHER),
    _entry(3, "No Stats", SHORTSTOP),
    _entry(4, "Signed Star", SHORTSTOP, new_team=METS, notes="Signed"),
    _entry(5, "Minor Leaguer", SHORTSTOP, notes=FreeAgency.MINOR_LEAGUE_NOTE),
    _entry(6, "Two Way", ("DH", "Hitter")),
]


def _sabermetrics(group: str, *wars: float) -> dict:
    """A sabermetrics block: a combined line first, as MLB sends for traded players."""
    splits = [{"stat": {"war": wars[0]}}] + [
        {"team": {"id": 1}, "stat": {"war": w}} for w in wars[1:]
    ]
    return {
        "type": {"displayName": "sabermetrics"},
        "group": {"displayName": group},
        "splits": splits,
    }


PEOPLE = {
    1: {"id": 1, "currentAge": 30, "stats": [_sabermetrics("hitting", 0.5)]},
    2: {"id": 2, "currentAge": 29, "stats": [_sabermetrics("pitching", 5.2086, 3.0, 2.2)]},
    3: {"id": 3, "currentAge": 22},
    4: {"id": 4, "currentAge": 31, "stats": [_sabermetrics("hitting", 7.0)]},
    5: {"id": 5, "currentAge": 24},
    6: {
        "id": 6,
        "currentAge": 31,
        "stats": [_sabermetrics("hitting", 2.0), _sabermetrics("pitching", 1.5)],
    },
}


def _api(classes: dict[int, list[dict]]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/freeAgents"):
            season = int(request.url.params["season"])
            return httpx.Response(200, json={"freeAgents": classes.get(season, [])})
        if path.endswith("/teams"):
            teams = [{"id": METS, "name": "New York Mets", "abbreviation": "NYM"}]
            return httpx.Response(200, json={"teams": teams})
        ids = [int(pid) for pid in request.url.params["personIds"].split(",")]
        return httpx.Response(200, json={"people": [PEOPLE[pid] for pid in ids]})

    return handler


async def test_best_available_major_leaguers_come_first(fake_mlb, call_tool):
    fake = fake_mlb(_api({SEASON: CLASS}))
    result = await call_tool("get_free_agents", {})

    rows = result.data["free_agents"]
    assert [(r["name"], r["war"]) for r in rows] == [
        ("High War", 5.209),  # the combined line of a traded player, rounded
        ("Two Way", 3.5),  # hitting and pitching WAR added together
        ("Low War", 0.5),
        ("No Stats", None),  # no MLB stats: listed last
    ]
    assert rows[0]["age"] == 29 and rows[0]["new_team"] is None
    assert result.data["season"] == SEASON
    people_request = fake.requests[-1]
    assert people_request.url.params["personIds"] == "1,2,3,6"  # only the matches
    assert "war" in people_request.url.params["fields"]


async def test_position_groups_and_exact_positions(fake_mlb, call_tool):
    fake_mlb(_api({SEASON: CLASS}))
    shortstops = await call_tool("get_free_agents", {"position": "SS"})
    pitchers = await call_tool("get_free_agents", {"position": "P"})
    assert [r["name"] for r in shortstops.data["free_agents"]] == ["Low War", "No Stats"]
    assert [r["name"] for r in pitchers.data["free_agents"]] == ["High War"]  # listed as SP


async def test_signed_players_for_a_team(fake_mlb, call_tool):
    fake_mlb(_api({SEASON: CLASS}))
    result = await call_tool("get_free_agents", {"status": "signed", "team": "Mets"})
    assert result.data["team"] == "New York Mets"
    [signed] = result.data["free_agents"]
    assert (signed["name"], signed["new_team"], signed["notes"]) == (
        "Signed Star",
        "New York Mets",
        "Signed",
    )


async def test_minor_leaguers_only_on_request(fake_mlb, call_tool):
    fake_mlb(_api({SEASON: CLASS}))
    result = await call_tool("get_free_agents", {"include_minor_leaguers": True, "status": "all"})
    assert result.data["total_matching"] == len(CLASS)


async def test_limit_is_explained(fake_mlb, call_tool):
    fake_mlb(_api({SEASON: CLASS}))
    result = await call_tool("get_free_agents", {"limit": 1})
    assert len(result.data["free_agents"]) == 1 and result.data["total_matching"] == 4
    assert "raise limit" in result.data["note"]


async def test_defaults_to_last_years_class_before_this_years_exists(fake_mlb, call_tool):
    fake = fake_mlb(_api({SEASON - 1: CLASS}))
    result = await call_tool("get_free_agents", {})
    assert result.data["season"] == SEASON - 1
    seasons = [r.url.params["season"] for r in fake.requests if r.url.path.endswith("/freeAgents")]
    assert seasons == [str(SEASON), str(SEASON - 1)]


async def test_no_matches_says_so_without_a_stats_request(fake_mlb, call_tool):
    fake = fake_mlb(_api({SEASON: CLASS}))
    result = await call_tool("get_free_agents", {"position": "C"})
    assert result.data["free_agents"] == [] and "match" in result.data["note"]
    assert not any(r.url.path.endswith("/people") for r in fake.requests)
