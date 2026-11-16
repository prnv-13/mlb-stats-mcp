"""Head-to-head tools: batter vs. pitcher history and side-by-side player comparisons."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from typing_extensions import NotRequired, TypedDict

from ..config import CacheTTL, GameType, Limits, Matchups
from ..mlb import endpoints, get_client
from . import advanced
from .common import (
    JSON,
    Better,
    HittingOrPitching,
    SeasonOrCareer,
    Stats,
    current_season,
    dig,
    overall_split,
    season_cache_ttl,
    stat_blocks,
)

# Stats kept for a batter-vs-pitcher matchup.
MATCHUP_FIELDS = (
    "plateAppearances", "atBats", "hits", "doubles", "triples", "homeRuns", "rbi",
    "baseOnBalls", "strikeOuts", "avg", "obp", "slg", "ops",
)  # fmt: skip

# Stats shown in a comparison, and which direction wins. None means context only
# (playing time), so no player is called the leader in it. Single-season comparisons
# add the advanced stats in advanced.FIELDS.
COMPARE_FIELDS: dict[str, dict[str, Better | None]] = {
    "hitting": {
        "gamesPlayed": None, "plateAppearances": None, "avg": "higher", "obp": "higher",
        "slg": "higher", "ops": "higher", "homeRuns": "higher", "rbi": "higher",
        "runs": "higher", "hits": "higher", "stolenBases": "higher", "baseOnBalls": "higher",
        "strikeOuts": "lower",
    },
    "pitching": {
        "gamesPlayed": None, "gamesStarted": None, "inningsPitched": "higher", "era": "lower",
        "whip": "lower", "wins": "higher", "losses": "lower", "saves": "higher",
        "strikeOuts": "higher", "strikeoutsPer9Inn": "higher", "walksPer9Inn": "lower",
        "homeRunsPer9": "lower",
    },
}  # fmt: skip

# Block names in a vsPlayer stats response.
CAREER_TOTALS_BLOCK = "vsPlayerTotal"
BY_SEASON_BLOCK = "vsPlayer"


# --------------------------------------------------------------- result types --


class PlayerRef(TypedDict):
    player_id: int
    name: str | None


class MatchupSeason(TypedDict):
    season: str | None
    game_type: str  # regular_season, wild_card, division_series, ...
    batter_team: str | None
    pitcher_team: str | None
    stats: Stats


class Matchup(TypedDict):
    """A batter's history against one pitcher."""

    batter: PlayerRef
    pitcher: PlayerRef
    career_totals: dict[str, Stats]  # keyed by game type, like MatchupSeason.game_type
    by_season: list[MatchupSeason]  # newest first
    note: NotRequired[str]


class ComparedPlayer(PlayerRef):
    position: str | None
    current_team: str | None
    stats: Stats  # single seasons include advanced stats such as war and fip
    played_for: NotRequired[list[str]]  # single-season comparisons only


class Comparison(TypedDict):
    """Players side by side; leaders maps each ranked stat to its leader's name, or "tie"."""

    group: HittingOrPitching
    stat_type: SeasonOrCareer
    season: int | None
    players: list[ComparedPlayer]
    leaders: dict[str, str]
    note: NotRequired[str]


# ------------------------------------------------------------------- helpers --


async def _people_by_id(player_ids: list[int], hydrate: str, ttl: int) -> dict[int, JSON]:
    """Fetch several players in one request, failing clearly on any unknown id."""
    data = await get_client().get(
        endpoints.PEOPLE,
        {"personIds": ",".join(map(str, player_ids)), "hydrate": hydrate},
        ttl=ttl,
    )
    found = {person["id"]: person for person in data.get("people", [])}
    missing = [pid for pid in player_ids if pid not in found]
    if missing:
        raise ToolError(f"No player with id {', '.join(map(str, missing))}. Use search_players.")
    return found


def _player_ref(person: JSON) -> PlayerRef:
    return {"player_id": person["id"], "name": person.get("fullName")}


def _pick(stats: JSON, fields: Iterable[str]) -> JSON:
    return {name: stats[name] for name in fields if name in stats}


def _as_number(value: Any) -> float | None:
    """Stats arrive as numbers or strings like ".312" or "158.2"; "-.--" means no value."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ matchups --


def _game_type_name(split: JSON) -> str:
    code = split.get("gameType", GameType.REGULAR_SEASON)
    return GameType.NAMES.get(code, code)


def _format_matchup_season(split: JSON) -> MatchupSeason:
    return {
        "season": split.get("season"),
        "game_type": _game_type_name(split),
        "batter_team": dig(split, "team", "name"),
        "pitcher_team": dig(split, "opponent", "name"),
        "stats": _pick(split.get("stat") or {}, MATCHUP_FIELDS),
    }


def _matchup_note(totals: dict[str, Stats]) -> str | None:
    regular_season = totals.get(GameType.NAMES[GameType.REGULAR_SEASON], {})
    plate_appearances = sum(t.get("plateAppearances", 0) for t in totals.values())
    if not plate_appearances:
        return "These players have never faced each other."
    if regular_season.get("plateAppearances", 0) < Matchups.MIN_MEANINGFUL_PLATE_APPEARANCES:
        return (
            f"Small sample (under {Matchups.MIN_MEANINGFUL_PLATE_APPEARANCES} plate appearances): "
            "head-to-head numbers this small say little about future results."
        )
    return None


async def get_matchup(batter_id: int, pitcher_id: int, include_postseason: bool = False) -> Matchup:
    """Get a batter's career history against one pitcher: plate appearances, hits, home runs,
    walks, strikeouts and AVG/OBP/SLG/OPS, in total and by season. Use for "how does X hit
    against Y?" and pitching or lineup matchup questions.

    Args:
        batter_id: The hitter's player id from search_players.
        pitcher_id: The pitcher's player id from search_players.
        include_postseason: Also include playoff meetings, reported separately by round.
    """
    people = await _people_by_id(
        [batter_id, pitcher_id], hydrate="currentTeam", ttl=CacheTTL.ROSTER
    )
    game_types = (GameType.REGULAR_SEASON,)
    if include_postseason:
        game_types += GameType.POSTSEASON_ROUNDS

    data = await get_client().get(
        endpoints.person_stats(batter_id),
        {
            "stats": "vsPlayer",
            "group": "hitting",
            "opposingPlayerId": pitcher_id,
            "gameType": ",".join(game_types),
        },
        ttl=CacheTTL.CURRENT_SEASON,
    )
    blocks = stat_blocks(data)
    totals = {
        _game_type_name(split): _pick(split.get("stat") or {}, MATCHUP_FIELDS)
        for split in blocks.get(CAREER_TOTALS_BLOCK, [])
    }
    by_season = sorted(
        (_format_matchup_season(split) for split in blocks.get(BY_SEASON_BLOCK, [])),
        key=lambda row: row["season"] or "",
        reverse=True,
    )

    result: Matchup = {
        "batter": _player_ref(people[batter_id]),
        "pitcher": _player_ref(people[pitcher_id]),
        "career_totals": totals,
        "by_season": by_season,
    }
    note = _matchup_note(totals)
    if note:
        result["note"] = note
    return result


# ---------------------------------------------------------------- comparison --


def _stats_hydration(
    group: HittingOrPitching, stat_type: SeasonOrCareer, season: int | None
) -> str:
    """The /people hydrate value that embeds each player's current team and stats.

    Single seasons also get the advanced stats types; MLB has no career version of them.
    """
    if stat_type == "season":
        types = ",".join((stat_type, *advanced.STAT_TYPES))
        return f"currentTeam,stats(group=[{group}],type=[{types}],season={season})"
    return f"currentTeam,stats(group=[{group}],type=[{stat_type}])"


def _format_compared_player(
    person: JSON, group: HittingOrPitching, stat_type: SeasonOrCareer
) -> ComparedPlayer:
    blocks = stat_blocks(person)
    splits = blocks.get(stat_type, [])
    overall = overall_split(splits)
    stats = _pick(overall.get("stat") or {}, COMPARE_FIELDS[group]) if overall else {}
    row: ComparedPlayer = {
        **_player_ref(person),
        "position": dig(person, "primaryPosition", "abbreviation"),
        "current_team": dig(person, "currentTeam", "name"),
        "stats": stats,
    }
    if stat_type == "season":
        stats.update(advanced.pick_advanced(blocks, group))
        row["played_for"] = [team for split in splits if (team := dig(split, "team", "name"))]
    return row


def _ranked_fields(group: HittingOrPitching) -> dict[str, Better | None]:
    advanced_fields = {name: stat.better for name, stat in advanced.FIELDS[group].items()}
    return {**COMPARE_FIELDS[group], **advanced_fields}


def _leaders(players: list[ComparedPlayer], group: HittingOrPitching) -> dict[str, str]:
    """For each stat with a better direction, the player who leads it ("tie" if shared)."""
    leaders = {}
    for stat, better in _ranked_fields(group).items():
        if better is None:
            continue
        values = {p["name"]: _as_number(p["stats"].get(stat)) for p in players}
        values = {name: value for name, value in values.items() if value is not None}
        if len(values) < Limits.MIN_COMPARE_PLAYERS:  # nobody to compare against
            continue
        best = max(values.values()) if better == "higher" else min(values.values())
        best_players = [name for name, value in values.items() if value == best]
        leaders[stat] = best_players[0] if len(best_players) == 1 else "tie"
    return leaders


async def compare_players(
    player_ids: list[int],
    group: HittingOrPitching = "hitting",
    stat_type: SeasonOrCareer = "season",
    season: int | None = None,
) -> Comparison:
    """Compare 2-5 players side by side for one season or their careers, and say who leads
    each stat (e.g. OPS, home runs, ERA, WHIP). Single seasons also compare WAR, wRC+, FIP
    and expected stats. Use for "who's better, X or Y?" questions.

    Args:
        player_ids: 2-5 player ids from search_players.
        group: "hitting" or "pitching".
        stat_type: "season" (one season) or "career" (career totals).
        season: Season year for stat_type="season"; defaults to the current one.
    """
    unique_ids = list(dict.fromkeys(player_ids))
    if not Limits.MIN_COMPARE_PLAYERS <= len(unique_ids) <= Limits.MAX_COMPARE_PLAYERS:
        raise ToolError(
            f"Pass between {Limits.MIN_COMPARE_PLAYERS} and {Limits.MAX_COMPARE_PLAYERS} "
            f"different player ids; got {len(unique_ids)}."
        )
    is_single_season = stat_type == "season"
    if is_single_season:
        season = season or current_season()

    found = await _people_by_id(
        unique_ids,
        hydrate=_stats_hydration(group, stat_type, season),
        ttl=season_cache_ttl(season) if is_single_season else CacheTTL.CURRENT_SEASON,
    )
    players = [_format_compared_player(found[pid], group, stat_type) for pid in unique_ids]
    result: Comparison = {
        "group": group,
        "stat_type": stat_type,
        "season": season if is_single_season else None,
        "players": players,
        "leaders": _leaders(players, group),
    }
    without_stats = [p["name"] for p in players if not p["stats"]]
    if without_stats:
        result["note"] = f"No {group} stats for {', '.join(without_stats)}" + (
            f" in {season}." if is_single_season else "."
        )
    return result
