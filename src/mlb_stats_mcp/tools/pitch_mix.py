"""A pitcher's pitch mix: how often he throws each pitch, how hard and with how much spin.

MLB serves this as two extra stats types for single seasons: pitchArsenal (usage and speed,
from 2008) and metricAverages (Statcast averages, from 2015; here only spin rate). Player
tools ask for them in the same request as the regular pitching stats.
"""

from __future__ import annotations

from typing_extensions import TypedDict

from .common import JSON, dig

ARSENAL = "pitchArsenal"
METRIC_AVERAGES = "metricAverages"
STAT_TYPES = (ARSENAL, METRIC_AVERAGES)
# metricAverages needs a metrics parameter naming what to average (MLB answers 500 without).
SPIN_METRIC = "releaseSpinRate"
PERCENT = 100
DECIMALS = 1


class Pitch(TypedDict):
    pitch: str | None  # e.g. "Four-seam FB"
    code: str | None  # MLB's pitch type code, e.g. "FF"
    usage_pct: float | None  # share of all his pitches that season
    count: int | None
    avg_speed_mph: float | None
    avg_spin_rpm: int | None  # Statcast, so None before 2015


def pick_pitch_mix(blocks: dict[str, list[JSON]]) -> list[Pitch]:
    """Each pitch, most used first, from a response split by common.stat_blocks."""
    spin_by_pitch = _spin_by_pitch(blocks.get(METRIC_AVERAGES, []))
    pitches = [
        _format_pitch(split.get("stat") or {}, spin_by_pitch) for split in blocks.get(ARSENAL, [])
    ]
    return sorted(pitches, key=lambda pitch: pitch["usage_pct"] or 0, reverse=True)


def _spin_by_pitch(splits: list[JSON]) -> dict[str, float]:
    """Pitch type code → average spin rate."""
    spin = {}
    for split in splits:
        stat = split.get("stat") or {}
        code = dig(stat, "event", "details", "type", "code")
        value = dig(stat, "metric", "averageValue")
        if code and value is not None and dig(stat, "metric", "name") == SPIN_METRIC:
            spin[code] = value
    return spin


def _format_pitch(stat: JSON, spin_by_pitch: dict[str, float]) -> Pitch:
    code = dig(stat, "type", "code")
    usage = stat.get("percentage")  # a fraction, e.g. 0.38
    speed = stat.get("averageSpeed")
    spin = spin_by_pitch.get(code)
    return {
        "pitch": dig(stat, "type", "description"),
        "code": code,
        "usage_pct": round(usage * PERCENT, DECIMALS) if usage is not None else None,
        "count": stat.get("count"),
        "avg_speed_mph": round(speed, DECIMALS) if speed is not None else None,
        "avg_spin_rpm": round(spin) if spin is not None else None,
    }
