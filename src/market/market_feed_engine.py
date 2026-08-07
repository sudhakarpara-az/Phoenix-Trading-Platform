"""
Market feed lifecycle coordinator.

This module manages connection state, subscriptions,
reconnect intent, and feed health at the platform level.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from threading import RLock

from src.market.subscription_manager import SubscriptionManager


class FeedState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    SUBSCRIBED = "SUBSCRIBED"
    RECONNECTING = "RECONNECTING"
    RECOVERING = "RECOVERING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class FeedHealth:
    state: FeedState
    last_message_at: datetime | None
    stale: bool
    subscription_count: int
    error: str | None = None


class MarketFeedEngine:
    """
    Coordinates market-feed state for Phoenix Trading Platform.

    It does not directly talk to Dhan.
    The Dhan WebSocket adapter will update this engine.
    """

    def __init__(
        self,
        subscription_manager: SubscriptionManager,
        stale_after_seconds: int = 5,
    ) -> None:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be greater than zero")

        self._subscriptions = subscription_manager
        self._stale_after = timedelta(seconds=stale_after_seconds)

        self._state = FeedState.DISCONNECTED
        self._last_message_at: datetime | None = None
        self._last_error: str | None = None

        self._lock = RLock()

    def set_connecting(self) -> None:
        with self._lock:
            self._state = FeedState.CONNECTING
            self._last_error = None

    def set_connected(self) -> None:
        with self._lock:
            self._state = FeedState.CONNECTED
            self._last_error = None

    def set_subscribed(self) -> None:
        with self._lock:
            self._state = FeedState.SUBSCRIBED
            self._last_error = None

    def set_reconnecting(self) -> None:
        with self._lock:
            self._state = FeedState.RECONNECTING

    def set_recovering(self) -> None:
        with self._lock:
            self._state = FeedState.RECOVERING

    def set_disconnected(self) -> None:
        with self._lock:
            self._state = FeedState.DISCONNECTED

    def set_error(self, message: str) -> None:
        if not message.strip():
            raise ValueError("error message cannot be empty")

        with self._lock:
            self._state = FeedState.ERROR
            self._last_error = message.strip()

    def mark_message_received(
        self,
        timestamp: datetime | None = None,
    ) -> None:
        with self._lock:
            self._last_message_at = timestamp or datetime.now()

    def state(self) -> FeedState:
        with self._lock:
            return self._state

    def is_connected(self) -> bool:
        with self._lock:
            return self._state in {
                FeedState.CONNECTED,
                FeedState.SUBSCRIBED,
            }

    def is_stale(
        self,
        now: datetime | None = None,
    ) -> bool:
        current_time = now or datetime.now()

        with self._lock:
            if self._last_message_at is None:
                return True

            return current_time - self._last_message_at > self._stale_after

    def health(
        self,
        now: datetime | None = None,
    ) -> FeedHealth:
        current_time = now or datetime.now()

        with self._lock:
            stale = (
                self._last_message_at is None
                or current_time - self._last_message_at > self._stale_after
            )

            return FeedHealth(
                state=self._state,
                last_message_at=self._last_message_at,
                stale=stale,
                subscription_count=self._subscriptions.count(),
                error=self._last_error,
            )