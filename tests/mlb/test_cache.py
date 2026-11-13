"""Tests for the generic TTL + LRU cache."""

from __future__ import annotations

import pytest

from mlb_stats_mcp.mlb.cache import TTLCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_entry_expires_after_ttl():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    cache.set("k", "v", ttl=10)
    clock.now += 9.9
    assert cache.get("k") == "v"
    clock.now += 0.2
    assert cache.get("k") is None
    assert len(cache) == 0  # expired entries are dropped on read


def test_least_recently_used_is_evicted():
    cache = TTLCache(max_entries=2, clock=FakeClock())
    cache.set("a", 1, ttl=60)
    cache.set("b", 2, ttl=60)
    cache.get("a")  # "a" is now more recent than "b"
    cache.set("c", 3, ttl=60)
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3


def test_zero_ttl_is_not_stored():
    cache = TTLCache(clock=FakeClock())
    cache.set("k", "v", ttl=0)
    assert cache.get("k") is None


def test_expires_at_and_iteration():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    cache.set("k", "v", ttl=30)
    assert cache.expires_at("k") == clock.now + 30
    assert cache.expires_at("missing") is None
    assert list(cache) == ["k"]


def test_max_entries_must_be_positive():
    with pytest.raises(ValueError):
        TTLCache(max_entries=0)
