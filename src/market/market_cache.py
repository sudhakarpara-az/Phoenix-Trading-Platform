"""
Thread-safe in-memory cache for latest market ticks.
"""

from __future__ import annotations

from threading import RLock

from src.market.market_types import MarketTick


class MarketCache:
    """
    Stores the latest MarketTick for each security_id.

    This class is intentionally broker-independent.
    """

    def __init__(self) -> None:
        self._ticks: dict[str, MarketTick] = {}
        self._lock = RLock()

    def update_tick(self, tick: MarketTick) -> None:
        """
        Store a tick if it is newer than the current cached tick.
        """

        with self._lock:
            current = self._ticks.get(tick.security_id)

            if current is not None and tick.timestamp < current.timestamp:
                return

            self._ticks[tick.security_id] = tick

    def get_tick(self, security_id: str) -> MarketTick | None:
        """
        Return the latest tick for a security_id.
        """

        with self._lock:
            return self._ticks.get(security_id)

    def get_ltp(self, security_id: str) -> float | None:
        """
        Return the latest traded price for a security_id.
        """

        with self._lock:
            tick = self._ticks.get(security_id)

            if tick is None:
                return None

            return tick.ltp

    def exists(self, security_id: str) -> bool:
        """Return whether the instrument exists in the cache."""

        with self._lock:
            return security_id in self._ticks

    def remove(self, security_id: str) -> bool:
        """
        Remove an instrument from the cache.

        Returns True if it existed.
        """

        with self._lock:
            return self._ticks.pop(security_id, None) is not None

    def clear(self) -> None:
        """Remove all cached ticks."""

        with self._lock:
            self._ticks.clear()

    def size(self) -> int:
        """Return the number of cached instruments."""

        with self._lock:
            return len(self._ticks)

    def snapshot(self) -> dict[str, MarketTick]:
        """
        Return a shallow copy of the current market state.

        MarketTick is immutable, so returning tick references here is safe.
        """

        with self._lock:
            return dict(self._ticks)