"""
Public market-data service for Phoenix Trading Platform.
"""

from __future__ import annotations

from src.market.market_cache import MarketCache
from src.market.market_types import MarketTick


class MarketDataService:
    """
    Provides read access to the latest normalized market data.

    Other application modules should depend on this service,
    not directly on MarketCache.
    """

    def __init__(self, cache: MarketCache) -> None:
        self._cache = cache

    def publish_tick(self, tick: MarketTick) -> None:
        """
        Publish a normalized market tick into the market-data layer.

        TickProcessor will call this method later.
        """

        self._cache.update_tick(tick)

    def get_tick(self, security_id: str) -> MarketTick | None:
        """Return the latest tick for a security ID."""

        return self._cache.get_tick(security_id)

    def get_ltp(self, security_id: str) -> float | None:
        """Return the latest traded price for a security ID."""

        return self._cache.get_ltp(security_id)

    def has_market_data(self, security_id: str) -> bool:
        """Return True when market data exists for the instrument."""

        return self._cache.exists(security_id)

    def remove(self, security_id: str) -> bool:
        """Remove one instrument from the current market state."""

        return self._cache.remove(security_id)

    def clear(self) -> None:
        """Clear all cached market data."""

        self._cache.clear()

    def snapshot(self) -> dict[str, MarketTick]:
        """Return a snapshot of the latest market state."""

        return self._cache.snapshot()

    def instrument_count(self) -> int:
        """Return number of instruments currently held."""

        return self._cache.size()
    