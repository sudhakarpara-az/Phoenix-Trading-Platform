"""
Thread-safe market data cache.
"""

from __future__ import annotations

from threading import Lock
from typing import Dict, Optional

from src.market.market_types import MarketTick


class MarketCache:
    """
    Stores the latest market tick for each instrument.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, MarketTick] = {}
        self._lock = Lock()

    def update(self, tick: MarketTick) -> None:
        """
        Add or update the latest tick.
        """
        with self._lock:
            self._cache[tick.security_id] = tick

    def get(self, security_id: str) -> Optional[MarketTick]:
        """
        Return the latest tick for an instrument.
        """
        with self._lock:
            return self._cache.get(security_id)

    def exists(self, security_id: str) -> bool:
        with self._lock:
            return security_id in self._cache

    def remove(self, security_id: str) -> None:
        with self._lock:
            self._cache.pop(security_id, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def get_all(self) -> Dict[str, MarketTick]:
        """
        Returns a copy of the cache.
        """
        with self._lock:
            return dict(self._cache)