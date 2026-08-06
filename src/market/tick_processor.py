"""
Tick Processor

Converts raw broker data into MarketTick objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.market.market_service import MarketService
from src.market.market_types import Exchange, MarketTick


class TickProcessor:
    """
    Processes raw market ticks from the broker.
    """

    def __init__(self, market_service: MarketService):
        self._market_service = market_service

    def process(self, raw_tick: dict[str, Any]) -> MarketTick:
        """
        Convert broker tick to MarketTick and store it.
        """

        tick = MarketTick(
            exchange=Exchange(raw_tick["exchange"]),
            symbol=raw_tick["symbol"],
            security_id=str(raw_tick["security_id"]),
            ltp=float(raw_tick["ltp"]),
            volume=int(raw_tick.get("volume", 0)),
            timestamp=datetime.now(),
        )

        self._market_service.update_tick(tick)

        return tick