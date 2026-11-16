"""Award tools: winners of MVP, Cy Young, Gold Glove and other MLB awards, and Hall of Fame
inductees."""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError
from typing_extensions import NotRequired, TypedDict

from ..config import Awards, CacheTTL, Limits
from ..mlb import endpoints, get_client
from .common import JSON, AwardName, LeagueCode, clamp, dig

ALL_LEAGUES = "MLB"


class AwardWinner(TypedDict):
    season: int
    league: LeagueCode  # "MLB" for awards given across both leagues
    player_id: int | None
    name: str | None
    position: str | None
    team: str | None  # the winner's team that season


class AwardWinners(TypedDict):
    """Winners from from_season to to_season, newest first."""

    award: AwardName
    leagues: list[LeagueCode]
    from_season: int
    to_season: int
    winners: list[AwardWinner]
    note: NotRequired[str]


class AwardCount(TypedDict):
    award: AwardName
    league: LeagueCode
    count: int
    seasons: list[int]


class PlayerAwards(TypedDict):
    player_id: int
    name: str | None
    awards: list[AwardCount]


# Reverse lookup for a player's award list: MLB award id → (award name, league code).
_AWARD_BY_ID: dict[str, tuple[str, str]] = {
    award_id: (award, league)
    for award, ids_by_league in Awards.IDS_BY_NAME.items()
    for league, award_id in ids_by_league.items()
}


def _award_ids(award: AwardName, league: LeagueCode) -> dict[str, str]:
    """The league → award id pairs to fetch for a request.

    MLB-wide awards ignore the league; league awards asked for "MLB" cover both leagues.
    """
    ids_by_league = Awards.IDS_BY_NAME[award]
    if league == ALL_LEAGUES or league not in ids_by_league:
        return ids_by_league
    return {league: ids_by_league[league]}


async def _recipients(award_id: str) -> list[JSON]:
    """Every winner of one award, all seasons. hydrate=team gives the team's name that year."""
    data = await get_client().get(
        endpoints.award_recipients(award_id), {"hydrate": "team"}, ttl=CacheTTL.AWARDS
    )
    return data.get("awards", [])


def _format_winner(recipient: JSON, league: LeagueCode) -> AwardWinner:
    return {
        "season": int(recipient["season"]),
        "league": league,
        "player_id": dig(recipient, "player", "id"),
        "name": dig(recipient, "player", "nameFirstLast"),
        "position": dig(recipient, "player", "primaryPosition", "abbreviation"),
        "team": dig(recipient, "team", "name"),
    }


def _unique(winners: list[AwardWinner]) -> list[AwardWinner]:
    """Some awards list a winner twice (e.g. once per voting body); keep one of each."""
    seen: set[tuple] = set()
    unique = []
    for winner in winners:
        key = (winner["season"], winner["league"], winner["player_id"])
        if key not in seen:
            seen.add(key)
            unique.append(winner)
    return unique


async def get_award_winners(
    award: AwardName,
    league: LeagueCode = "MLB",
    season: int | None = None,
    seasons: int = Limits.DEFAULT_AWARD_SEASONS,
) -> AwardWinners:
    """Get the winners of an MLB award, newest season first.

    Args:
        award: Which award, e.g. "mvp", "cy_young", "rookie_of_the_year", "gold_glove",
            "silver_slugger", "world_series_mvp", or "hall_of_fame" (by induction year).
        league: "AL", "NL" or "MLB" (both leagues). Ignored for awards given across all of
            MLB, such as world_series_mvp.
        season: Season year. Defaults to the most recent season with a winner.
        seasons: How many seasons to include, counting back from season (1-100). For example
            season=2026, seasons=10 returns the 2017-2026 winners.
    """
    ids_by_league = _award_ids(award, league)
    winners = []
    for award_league, award_id in ids_by_league.items():
        winners += [_format_winner(r, award_league) for r in await _recipients(award_id)]
    winners = _unique(winners)

    if not winners:
        raise ToolError(f"No winners found for award '{award}'.")

    last_season = season or max(w["season"] for w in winners)
    first_season = last_season - clamp(seasons, 1, Limits.MAX_AWARD_SEASONS) + 1
    in_range = [w for w in winners if first_season <= w["season"] <= last_season]
    in_range.sort(key=lambda w: (-w["season"], w["league"]))

    result: AwardWinners = {
        "award": award,
        "leagues": list(ids_by_league),
        "from_season": first_season,
        "to_season": last_season,
        "winners": in_range,
    }
    if not in_range:
        period = (
            str(last_season) if first_season == last_season else f"{first_season}-{last_season}"
        )
        result["note"] = (
            f"No {award} winners recorded for {period}. "
            "Most awards are announced in November, after the season ends; Hall of Fame "
            "classes are elected in January and inducted in July."
        )
    return result


async def get_player_awards(player_id: int) -> PlayerAwards:
    """Get the major MLB awards a player has won (MVP, Cy Young, Gold Glove, All-Star, Hall of
    Fame and so on), with the seasons for each.

    Args:
        player_id: MLB player id from search_players.
    """
    data = await get_client().get(
        endpoints.person(player_id), {"hydrate": "awards"}, ttl=CacheTTL.AWARDS
    )
    people = data.get("people") or []
    if not people:
        raise ToolError(f"No player with id {player_id}")
    person = people[0]

    # The API also lists minor-league and weekly honors; keep only the awards in our catalog.
    seasons_by_award: dict[tuple[str, str], set[int]] = {}
    for entry in person.get("awards", []):
        known = _AWARD_BY_ID.get(entry.get("id"))
        if known:
            seasons_by_award.setdefault(known, set()).add(int(entry["season"]))

    catalog_order = list(_AWARD_BY_ID.values())
    awards = [
        {"award": award, "league": league, "count": len(seasons), "seasons": sorted(seasons)}
        for (award, league), seasons in sorted(
            seasons_by_award.items(), key=lambda item: catalog_order.index(item[0])
        )
    ]
    return {"player_id": player_id, "name": person.get("fullName"), "awards": awards}
