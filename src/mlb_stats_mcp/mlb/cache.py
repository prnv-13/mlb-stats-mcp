"""A small in-memory LRU cache with a per-entry time-to-live.

Generic on purpose: it knows nothing about HTTP or MLB, so it can be unit-tested alone
and swapped for a library (cachetools, aiocache + Redis) without touching callers.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterator
from typing import Any

from ..config import Cache


class TTLCache:
    """LRU cache whose entries expire `ttl` seconds after they are set.

    - Expiry is checked lazily on read; an expired entry counts as a miss and is dropped.
    - When more than `max_entries` are stored, the least recently used entry is evicted.
    - `clock` is injectable so tests can move time forward without sleeping.
    """

    def __init__(
        self,
        max_entries: int = Cache.MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Any | None:
        entry = self._data.get(key)
        if entry is None or entry[0] <= self._clock():
            if entry is not None:
                del self._data[key]
            self.misses += 1
            return None
        self._data.move_to_end(key)  # mark as recently used
        self.hits += 1
        return entry[1]

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        self._data[key] = (self._clock() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)  # evict least recently used

    def expires_at(self, key: Hashable) -> float | None:
        """Clock time at which `key` expires, or None if it isn't stored."""
        entry = self._data.get(key)
        return entry[0] if entry else None

    def clear(self) -> None:
        self._data.clear()
        self.hits = self.misses = 0

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[Hashable]:
        return iter(list(self._data))
