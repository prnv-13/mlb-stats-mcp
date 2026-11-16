"""Advanced stats: sabermetrics (WAR, wRC+, FIP, ...) and Statcast expected stats.

MLB serves these as two extra stats types, for single seasons only. Player tools ask for
them in the same request as the regular stats and use pick_advanced to read them out.
"""

from __future__ import annotations

from dataclasses import dataclass

from .common import JSON, Better, HittingOrPitching, Stats, overall_split, stat_blocks

SABERMETRICS = "sabermetrics"
EXPECTED = "expectedStatistics"
STAT_TYPES = (SABERMETRICS, EXPECTED)
DECIMALS = 3  # sabermetrics arrive with ~6 decimals


@dataclass(frozen=True)
class AdvancedStat:
    stat_type: str  # the MLB stats type it comes from
    field: str  # MLB's name for it in that type
    better: Better


# Our name → where to find it. Expected stats for a pitcher are what hitters did against him.
FIELDS: dict[str, dict[str, AdvancedStat]] = {
    "hitting": {
        "war": AdvancedStat(SABERMETRICS, "war", "higher"),
        "wRcPlus": AdvancedStat(SABERMETRICS, "wRcPlus", "higher"),
        "woba": AdvancedStat(SABERMETRICS, "woba", "higher"),
        "xba": AdvancedStat(EXPECTED, "avg", "higher"),
        "xslg": AdvancedStat(EXPECTED, "slg", "higher"),
        "xwoba": AdvancedStat(EXPECTED, "woba", "higher"),
    },
    "pitching": {
        "war": AdvancedStat(SABERMETRICS, "war", "higher"),
        "fip": AdvancedStat(SABERMETRICS, "fip", "lower"),
        "xfip": AdvancedStat(SABERMETRICS, "xfip", "lower"),
        "eraMinus": AdvancedStat(SABERMETRICS, "eraMinus", "lower"),
        "fipMinus": AdvancedStat(SABERMETRICS, "fipMinus", "lower"),
        "xba": AdvancedStat(EXPECTED, "avg", "lower"),
        "xslg": AdvancedStat(EXPECTED, "slg", "lower"),
        "xwoba": AdvancedStat(EXPECTED, "woba", "lower"),
    },
}


def pick_advanced(blocks: dict[str, list[JSON]], group: HittingOrPitching) -> Stats:
    """The advanced stats for one season, from a response split by common.stat_blocks."""
    lines = {
        stat_type: (overall_split(blocks.get(stat_type, [])) or {}).get("stat") or {}
        for stat_type in STAT_TYPES
    }
    picked: Stats = {}
    for name, stat in FIELDS[group].items():
        value = lines[stat.stat_type].get(stat.field)
        if value is not None:
            picked[name] = _rounded(value) if isinstance(value, float) else value
    return picked


def season_war(person: JSON) -> float | None:
    """WAR for a person hydrated with sabermetrics, hitting and pitching added together
    (so a two-way player gets credit for both). None if they have no MLB stats."""
    wars = []
    for group in FIELDS:
        line = overall_split(stat_blocks(person, group).get(SABERMETRICS, [])) or {}
        war = (line.get("stat") or {}).get("war")
        if war is not None:
            wars.append(war)
    return _rounded(sum(wars)) if wars else None


def _rounded(value: float) -> float:
    return round(value, DECIMALS) + 0.0  # + 0.0 turns -0.0 into 0.0
