"""
Market Service

Provides a single interface for all market data operations.
"""

from __future__ import annotations

from typing import Optional

from src.market.market_cache import MarketCache
from src.market.market_types import MarketTick


class MarketService:
    """
    Service layer for market data.
    """

    def __init__(self) -> None:
        self._cache = MarketCache()

    def update_tick(self, tick: MarketTick) -> None:
        """
        Update latest market tick.
        """
        self._cache.update_tick(tick)

    def get_tick(self, security_id: str) -> Optional[MarketTick]:
        """
        Return latest MarketTick.
        """
        return self._cache.get(security_id)

    def get_ltp(self, security_id: str) -> Optional[float]:
        """
        Return latest traded price.
        """
        tick = self._cache.get(security_id)

        if tick is None:
            return None

        return tick.ltp

    def exists(self, security_id: str) -> bool:
        return self._cache.exists(security_id)

    def clear(self) -> None:
        self._cache.clear()

    def cache_size(self) -> int:
        return self._cache.size()