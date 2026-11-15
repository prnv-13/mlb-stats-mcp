"""Transactions tool: signings, trades, waivers, injured list moves and call-ups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from mcp.server.mcpserver.exceptions import ToolError

from ..config import CacheTTL, Limits, MLBApi, Transactions
from ..mlb import endpoints, get_client
from .common import ISO_DATE_FORMAT, JSON, TransactionKind, clamp, dig, parse_date, today_date
from .teams import resolve_team

ALL_KINDS = "all"


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _resolve_date_range(
    start_date: str | None, end_date: str | None, *, whole_history: bool
) -> DateRange | None:
    """Turn optional start/end arguments into a concrete range.

    Returns None when no dates were given and the caller wants a player's whole history.
    """
    if start_date is None and end_date is None and whole_history:
        return None

    window = timedelta(days=Transactions.DEFAULT_WINDOW_DAYS - 1)
    end = parse_date(end_date, "end_date") if end_date else today_date()
    start = parse_date(start_date, "start_date") if start_date else end - window
    if start > end:
        raise ToolError(f"start_date ({start}) is after end_date ({end}).")
    return DateRange(start, end)


def _format_transaction(transaction: JSON) -> JSON:
    return {
        "date": transaction.get("date"),
        "type": transaction.get("typeDesc"),
        "player_id": dig(transaction, "person", "id"),
        "player": dig(transaction, "person", "fullName"),
        "from_team": dig(transaction, "fromTeam", "name"),
        "to_team": dig(transaction, "toTeam", "name"),
        "description": transaction.get("description"),
    }


def _matches_kind(transaction: JSON, kind: TransactionKind) -> bool:
    if kind == ALL_KINDS:
        return True
    return transaction.get("typeCode") in Transactions.TYPE_CODES_BY_KIND[kind]


def _newest_first(transaction: JSON) -> tuple[str, int]:
    return transaction.get("date", ""), transaction.get("id", 0)


async def get_transactions(
    team: str | None = None,
    player_id: int | None = None,
    kind: TransactionKind = "all",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Limits.DEFAULT_TRANSACTIONS,
) -> JSON:
    """Get MLB roster moves, newest first: free-agent signings, trades, waiver claims,
    designations for assignment, releases, injured list moves and call-ups. Use this for
    off-season "hot stove" questions like "who did the Yankees sign?" or "was he traded?".

    Args:
        team: Only moves involving this team (name, abbreviation or id).
        player_id: Only moves involving this player (id from search_players). Without dates,
            returns the player's whole transaction history.
        kind: "all", "signings", "trades", "free_agency" (players filing for free agency),
            "waivers_and_dfa", "releases", "status_changes" (injured list placements and
            activations) or "call_ups_and_options".
        start_date: First day, YYYY-MM-DD. Defaults to 7 days before end_date.
        end_date: Last day, YYYY-MM-DD. Defaults to today.
        limit: Maximum number of moves to return (1-200).
    """
    resolved_team = await resolve_team(team) if team else None
    date_range = _resolve_date_range(start_date, end_date, whole_history=player_id is not None)

    is_league_wide = resolved_team is None and player_id is None
    if is_league_wide and date_range and date_range.days > Transactions.MAX_LEAGUE_WIDE_WINDOW_DAYS:
        raise ToolError(
            f"A search across all teams can cover at most "
            f"{Transactions.MAX_LEAGUE_WIDE_WINDOW_DAYS} days. Narrow the dates, or pass a team "
            "or player_id."
        )

    is_finished_range = date_range is not None and date_range.end < today_date()
    data = await get_client().get(
        endpoints.TRANSACTIONS,
        {
            "sportId": MLBApi.SPORT_ID_MLB,
            "teamId": resolved_team["id"] if resolved_team else None,
            "playerId": player_id,
            "startDate": date_range.start.strftime(ISO_DATE_FORMAT) if date_range else None,
            "endDate": date_range.end.strftime(ISO_DATE_FORMAT) if date_range else None,
        },
        ttl=CacheTTL.ROSTER if is_finished_range else CacheTTL.RECENT_TRANSACTIONS,
    )

    matching = [t for t in data.get("transactions", []) if _matches_kind(t, kind)]
    matching.sort(key=_newest_first, reverse=True)
    shown = matching[: clamp(limit, 1, Limits.MAX_TRANSACTIONS)]

    result: JSON = {
        "team": resolved_team["name"] if resolved_team else None,
        "player_id": player_id,
        "kind": kind,
        "start_date": str(date_range.start) if date_range else None,
        "end_date": str(date_range.end) if date_range else None,
        "total_matching": len(matching),
        "transactions": [_format_transaction(t) for t in shown],
    }
    if len(shown) < len(matching):
        result["note"] = f"Showing the {len(shown)} most recent; raise limit or narrow the dates."
    elif not matching:
        result["note"] = "No matching transactions in this period."
    return result
