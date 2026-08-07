"""
Normalize raw Dhan market-feed messages into Phoenix MarketTick objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.market.market_data_service import MarketDataService
from src.market.market_types import (
    Instrument,
    MarketTick,
    TickType,
)
from src.market.subscription_manager import SubscriptionManager


class TickProcessor:
    """
    Converts Dhan-specific market-feed messages into
    broker-independent Phoenix MarketTick objects.
    """

    def __init__(
        self,
        market_data_service: MarketDataService,
        subscription_manager: SubscriptionManager,
    ) -> None:
        self._market_data = market_data_service
        self._subscriptions = subscription_manager

    def process(self, message: Any) -> MarketTick | None:
        """
        Normalize one raw Dhan message.

        Returns:
            MarketTick when the message contains usable price data.
            None for packets that Phoenix does not treat as market ticks.
        """

        if not isinstance(message, dict):
            return None

        security_id = self._extract_security_id(message)

        if security_id is None:
            return None

        instrument = self._find_instrument(security_id)

        if instrument is None:
            return None

        ltp = self._extract_ltp(message)

        if ltp is None or ltp <= 0:
            return None

        tick_type = self._extract_tick_type(message)

        if tick_type is None:
            return None

        timestamp = self._extract_timestamp(message)

        volume = self._extract_volume(message)

        tick = MarketTick(
            exchange=instrument.exchange,
            symbol=instrument.symbol,
            security_id=instrument.security_id,
            ltp=ltp,
            volume=volume,
            timestamp=timestamp,
            tick_type=tick_type,
        )

        self._market_data.publish_tick(tick)

        return tick

    def _find_instrument(
        self,
        security_id: str,
    ) -> Instrument | None:
        """
        Resolve a subscribed Phoenix instrument by security_id.

        For current NIFTY-only scope this is sufficient.
        Later, if security IDs overlap across exchanges, we will
        resolve using exchange + security_id.
        """

        for subscription in self._subscriptions.list_all():
            instrument = subscription.instrument

            if instrument.security_id == security_id:
                return instrument

        return None

    @staticmethod
    def _extract_security_id(
        message: dict[str, Any],
    ) -> str | None:
        value = (
            message.get("security_id")
            or message.get("securityId")
            or message.get("SecurityId")
        )

        if value is None:
            return None

        security_id = str(value).strip()

        return security_id or None

    @staticmethod
    def _extract_ltp(
        message: dict[str, Any],
    ) -> float | None:
        value = None

        for key in (
            "LTP",
            "ltp",
            "last_price",
            "last_traded_price",
        ):
            if key in message:
                value = message[key]
                break

        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_volume(
        message: dict[str, Any],
    ) -> int:
        """
        Ticker packets may not contain volume.

        In that case Phoenix stores 0 rather than rejecting
        an otherwise valid price tick.
        """

        value = None

        for key in (
            "volume",
            "Volume",
            "volume_traded_today",
        ):
            if key in message:
                value = message[key]
                break

        if value is None:
            return 0

        try:
            volume = int(value)
        except (TypeError, ValueError):
            return 0

        return max(volume, 0)

    @staticmethod
    def _extract_timestamp(
        message: dict[str, Any],
    ) -> datetime:
        """
        Normalize Dhan epoch timestamps where present.

        If the decoded SDK message does not expose an exchange
        timestamp, use Phoenix receipt time.
        """

        value = None

        for key in (
            "LTT",
            "ltt",
            "last_trade_time",
            "timestamp",
        ):
            if key in message:
                value = message[key]
                break

        if value is None:
            return datetime.now()

        if isinstance(value, datetime):
            return value

        try:
            epoch = float(value)

            # Defensive handling if milliseconds are ever supplied.
            if epoch > 10_000_000_000:
                epoch /= 1000

            return datetime.fromtimestamp(epoch)

        except (TypeError, ValueError, OSError):
            return datetime.now()

    @staticmethod
    def _extract_tick_type(
        message: dict[str, Any],
    ) -> TickType | None:
        """
        Identify usable Dhan market packet types.

        Handles both decoded textual packet names and common
        numeric Dhan response codes.
        """

        raw_type = (
            message.get("type")
            or message.get("packet_type")
            or message.get("response_code")
        )

        if raw_type is None:
            # If a message contains valid LTP but no explicit
            # packet label, treat it conservatively as LTP.
            return TickType.LTP

        if isinstance(raw_type, int):
            mapping = {
                2: TickType.LTP,
                4: TickType.QUOTE,
                8: TickType.FULL,
            }

            return mapping.get(raw_type)

        normalized = str(raw_type).strip().lower()

        if "ticker" in normalized:
            return TickType.LTP

        if "quote" in normalized:
            return TickType.QUOTE

        if "full" in normalized:
            return TickType.FULL

        return None