"""Draft tool: MLB draft picks by year, round or team."""

from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict

from ..config import Limits
from ..mlb import endpoints, get_client
from .common import JSON, clamp, current_season, dig, season_cache_ttl
from .teams import resolve_team


class DraftPick(TypedDict):
    pick: int | None  # overall pick number
    round: str | None
    round_pick: int | None
    team: str | None
    player_id: int | None
    name: str | None
    position: str | None
    school: str | None
    school_class: str | None  # e.g. "HS SR" (high school senior) or "4YR JR" (college junior)
    signing_bonus: int | None  # dollars
    slot_value: int | None  # MLB's assigned value for the pick, in dollars


class Draft(TypedDict):
    """Draft picks in order. Rounds are numbered, plus extra rounds such as "CB-A"."""

    season: int
    round: str | None
    team: str | None
    total_picks: int
    picks: list[DraftPick]
    note: NotRequired[str]


def _dollars(value: Any) -> int | None:
    """Money arrives as a string like "10350000", or not at all for unsigned picks."""
    return int(value) if value else None


def _format_pick(pick: JSON) -> DraftPick:
    return {
        "pick": pick.get("pickNumber"),
        "round": pick.get("pickRound"),
        "round_pick": pick.get("roundPickNumber"),
        "team": dig(pick, "team", "name"),
        "player_id": dig(pick, "person", "id"),
        "name": dig(pick, "person", "fullName"),
        "position": dig(pick, "person", "primaryPosition", "abbreviation"),
        "school": dig(pick, "school", "name"),
        "school_class": dig(pick, "school", "schoolClass"),
        "signing_bonus": _dollars(pick.get("signingBonus")),
        "slot_value": _dollars(pick.get("pickValue")),
    }


async def _draft_picks(season: int, round: str | None, team_id: int | None) -> list[JSON]:
    data = await get_client().get(
        endpoints.draft(season),
        {"round": round, "teamId": team_id},
        ttl=season_cache_ttl(season),
    )
    rounds = dig(data, "drafts", "rounds") or []
    picks = [pick for draft_round in rounds for pick in draft_round.get("picks", [])]
    # The list also has passed picks and, before the draft, unfilled slots.
    return [pick for pick in picks if pick.get("isDrafted") and not pick.get("isPass")]


async def get_draft(
    season: int | None = None,
    round: str | None = None,
    team: str | None = None,
    limit: int = Limits.DEFAULT_DRAFT_PICKS,
) -> Draft:
    """Get MLB draft picks: overall pick, round, team, player, position, school and signing
    bonus. Use for "who went first overall?" or "who did the Yankees draft?".

    Args:
        season: Draft year. Defaults to the latest draft (it is held each July).
        round: Only this round, e.g. "1", "2" or a compensation round such as "CB-A".
        team: Only this team's picks (name, abbreviation or id).
        limit: How many picks to return, in draft order (1-700).
    """
    resolved_team = await resolve_team(team) if team else None
    team_id = resolved_team["id"] if resolved_team else None
    requested = season or current_season()
    picks = await _draft_picks(requested, round, team_id)
    if not picks and season is None:  # this year's draft hasn't happened yet
        requested -= 1
        picks = await _draft_picks(requested, round, team_id)

    picks.sort(key=lambda pick: pick.get("pickNumber") or 0)
    shown = picks[: clamp(limit, 1, Limits.MAX_DRAFT_PICKS)]
    result: Draft = {
        "season": requested,
        "round": round,
        "team": resolved_team["name"] if resolved_team else None,
        "total_picks": len(picks),
        "picks": [_format_pick(pick) for pick in shown],
    }
    if not picks:
        result["note"] = f"No {requested} draft picks match these filters."
    elif len(shown) < len(picks):
        result["note"] = f"Showing the first {len(shown)} picks; raise limit to see more."
    return result
