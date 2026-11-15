from __future__ import annotations

import time
from datetime import timedelta

import httpx
import pytest

from mlb_stats_mcp.config import CacheTTL, Transactions
from mlb_stats_mcp.tools.common import today_date

pytestmark = pytest.mark.anyio


def _move(transaction_id: int, date: str, type_code: str, type_desc: str) -> dict:
    return {
        "id": transaction_id,
        "date": date,
        "typeCode": type_code,
        "typeDesc": type_desc,
        "person": {"id": transaction_id, "fullName": f"Player {transaction_id}"},
        "toTeam": {"id": 147, "name": "New York Yankees"},
        "description": f"{type_desc} on {date}",
    }


MOVES = {
    "transactions": [
        _move(1, "2026-11-01", "SFA", "Signed as Free Agent"),
        _move(2, "2026-11-03", "TR", "Trade"),
        _move(3, "2026-11-02", "SC", "Status Change"),
        _move(4, "2026-11-04", "DES", "Designated for Assignment"),
    ]
}


def _serve_moves(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=MOVES)


async def test_moves_come_back_newest_first(fake_mlb, call_tool):
    fake_mlb(_serve_moves)
    result = await call_tool(
        "get_transactions", {"start_date": "2026-11-01", "end_date": "2026-11-07"}
    )
    assert [t["date"] for t in result.data["transactions"]] == [
        "2026-11-04", "2026-11-03", "2026-11-02", "2026-11-01",
    ]  # fmt: skip


async def test_kind_filters_by_type_code(fake_mlb, call_tool):
    fake_mlb(_serve_moves)
    result = await call_tool(
        "get_transactions",
        {"kind": "waivers_and_dfa", "start_date": "2026-11-01", "end_date": "2026-11-07"},
    )
    assert [t["type"] for t in result.data["transactions"]] == ["Designated for Assignment"]


async def test_limit_truncates_and_says_so(fake_mlb, call_tool):
    fake_mlb(_serve_moves)
    result = await call_tool(
        "get_transactions", {"limit": 2, "start_date": "2026-11-01", "end_date": "2026-11-07"}
    )
    assert len(result.data["transactions"]) == 2
    assert result.data["total_matching"] == 4
    assert "most recent" in result.data["note"]


async def test_default_window_is_the_last_week(fake_mlb, call_tool):
    fake = fake_mlb(_serve_moves)
    await call_tool("get_transactions", {})
    params = fake.requests[0].url.params
    week_ago = today_date() - timedelta(days=Transactions.DEFAULT_WINDOW_DAYS - 1)
    assert params["endDate"] == str(today_date())
    assert params["startDate"] == str(week_ago)


async def test_player_without_dates_gets_whole_history(fake_mlb, call_tool):
    fake = fake_mlb(_serve_moves)
    await call_tool("get_transactions", {"player_id": 592450})
    params = fake.requests[0].url.params
    assert params["playerId"] == "592450"
    assert "startDate" not in params and "endDate" not in params


async def test_league_wide_search_is_capped(fake_mlb, call_tool):
    fake = fake_mlb(_serve_moves)
    result = await call_tool(
        "get_transactions", {"start_date": "2026-01-01", "end_date": "2026-06-30"}
    )
    assert result.is_error and str(Transactions.MAX_LEAGUE_WIDE_WINDOW_DAYS) in result.text
    assert not fake.requests  # rejected before calling MLB


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start_date": "Nov 1"}, "start_date must be a date"),
        ({"start_date": "2026-11-05", "end_date": "2026-11-01"}, "is after end_date"),
    ],
)
async def test_bad_dates_are_explained(fake_mlb, call_tool, arguments, message):
    fake_mlb(_serve_moves)
    result = await call_tool("get_transactions", arguments)
    assert result.is_error and message in result.text


async def test_finished_ranges_are_cached_longer_than_ranges_ending_today(fake_mlb, call_tool):
    fake = fake_mlb(_serve_moves)
    await call_tool("get_transactions", {"start_date": "2026-01-01", "end_date": "2026-01-07"})
    await call_tool("get_transactions", {})

    cache = fake.client.cache
    past_range, recent_range = list(cache)  # cache keys in insertion order
    assert cache.expires_at(past_range) - time.monotonic() > CacheTTL.RECENT_TRANSACTIONS
    assert cache.expires_at(recent_range) - time.monotonic() <= CacheTTL.RECENT_TRANSACTIONS
