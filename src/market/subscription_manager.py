"""
Subscription Manager

Maintains the list of subscribed instruments.
"""

from __future__ import annotations

from typing import Dict, List

from src.market.market_types import Instrument


class SubscriptionManager:
    """
    Manages market data subscriptions.
    """

    def __init__(self) -> None:
        self._subscriptions: Dict[str, Instrument] = {}

    def subscribe(self, instrument: Instrument) -> None:
        self._subscriptions[instrument.security_id] = instrument

    def unsubscribe(self, security_id: str) -> None:
        self._subscriptions.pop(security_id, None)

    def is_subscribed(self, security_id: str) -> bool:
        return security_id in self._subscriptions

    def get(self, security_id: str) -> Instrument | None:
        return self._subscriptions.get(security_id)

    def get_all(self) -> List[Instrument]:
        return list(self._subscriptions.values())

    def clear(self) -> None:
        self._subscriptions.clear()

    def count(self) -> int:
        return len(self._subscriptions)