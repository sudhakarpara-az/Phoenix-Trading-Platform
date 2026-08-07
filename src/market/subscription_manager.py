"""
Broker-independent market subscription management.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from src.market.market_types import Exchange, Instrument, TickType


@dataclass(frozen=True, slots=True)
class MarketSubscription:
    """
    Represents one active market-data subscription.
    """

    instrument: Instrument
    tick_type: TickType

    @property
    def key(self) -> str:
        """
        Return the unique subscription key.
        """

        return (
            f"{self.instrument.exchange.value}:"
            f"{self.instrument.security_id}"
        )


class SubscriptionManager:
    """
    Maintains active market-data subscriptions.

    The manager is broker-independent and thread-safe.
    """

    _TICK_PRIORITY: dict[TickType, int] = {
        TickType.LTP: 1,
        TickType.QUOTE: 2,
        TickType.FULL: 3,
    }

    def __init__(self) -> None:
        self._subscriptions: dict[str, MarketSubscription] = {}
        self._lock = RLock()

    def add(
        self,
        instrument: Instrument,
        tick_type: TickType = TickType.LTP,
    ) -> MarketSubscription:
        """
        Add or upgrade a market subscription.

        If an instrument is already subscribed with a higher or equal
        subscription mode, the existing subscription is retained.
        """

        subscription = MarketSubscription(
            instrument=instrument,
            tick_type=tick_type,
        )

        with self._lock:
            existing = self._subscriptions.get(subscription.key)

            if existing is None:
                self._subscriptions[subscription.key] = subscription
                return subscription

            existing_priority = self._TICK_PRIORITY[existing.tick_type]
            requested_priority = self._TICK_PRIORITY[tick_type]

            if requested_priority > existing_priority:
                self._subscriptions[subscription.key] = subscription
                return subscription

            return existing

    def remove(
        self,
        exchange: Exchange,
        security_id: str,
    ) -> bool:
        """
        Remove one subscription.

        Returns True when the subscription existed.
        """

        key = self._build_key(exchange, security_id)

        with self._lock:
            return self._subscriptions.pop(key, None) is not None

    def get(
        self,
        exchange: Exchange,
        security_id: str,
    ) -> MarketSubscription | None:
        """
        Return one active subscription.
        """

        key = self._build_key(exchange, security_id)

        with self._lock:
            return self._subscriptions.get(key)

    def contains(
        self,
        exchange: Exchange,
        security_id: str,
    ) -> bool:
        """
        Return whether an instrument is subscribed.
        """

        key = self._build_key(exchange, security_id)

        with self._lock:
            return key in self._subscriptions

    def list_all(self) -> tuple[MarketSubscription, ...]:
        """
        Return an immutable snapshot of all subscriptions.
        """

        with self._lock:
            return tuple(self._subscriptions.values())

    def list_by_exchange(
        self,
        exchange: Exchange,
    ) -> tuple[MarketSubscription, ...]:
        """
        Return all subscriptions for one exchange.
        """

        with self._lock:
            return tuple(
                subscription
                for subscription in self._subscriptions.values()
                if subscription.instrument.exchange is exchange
            )

    def count(self) -> int:
        """
        Return the number of active subscriptions.
        """

        with self._lock:
            return len(self._subscriptions)

    def clear(self) -> None:
        """
        Remove all active subscriptions.
        """

        with self._lock:
            self._subscriptions.clear()

    @staticmethod
    def _build_key(
        exchange: Exchange,
        security_id: str,
    ) -> str:
        normalized_security_id = security_id.strip()

        if not normalized_security_id:
            raise ValueError("security_id cannot be empty")

        return f"{exchange.value}:{normalized_security_id}"