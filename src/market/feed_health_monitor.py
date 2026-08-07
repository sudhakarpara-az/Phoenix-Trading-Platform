"""
Market-feed health monitoring.

Tracks message freshness, packet counts,
reconnect counts, and current feed health.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from threading import RLock


class FeedHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class FeedHealthSnapshot:
    state: FeedHealthState
    last_message_at: datetime | None
    messages_received: int
    reconnect_count: int
    stale_after_seconds: int
    error: str | None


class FeedHealthMonitor:
    """
    Tracks health statistics for the live market feed.
    """

    def __init__(self, stale_after_seconds: int = 5) -> None:
        if stale_after_seconds <= 0:
            raise ValueError(
                "stale_after_seconds must be greater than zero"
            )

        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._stale_after_seconds = stale_after_seconds

        self._last_message_at: datetime | None = None
        self._messages_received = 0
        self._reconnect_count = 0

        self._connected = False
        self._error: str | None = None

        self._lock = RLock()

    def mark_connected(self) -> None:
        with self._lock:
            self._connected = True
            self._error = None

    def mark_disconnected(self) -> None:
        with self._lock:
            self._connected = False

    def mark_message_received(
        self,
        timestamp: datetime | None = None,
    ) -> None:
        with self._lock:
            self._last_message_at = timestamp or datetime.now()
            self._messages_received += 1

    def mark_reconnect(self) -> None:
        with self._lock:
            self._reconnect_count += 1

    def mark_error(self, message: str) -> None:
        if not message.strip():
            raise ValueError("error message cannot be empty")

        with self._lock:
            self._error = message.strip()

    def clear_error(self) -> None:
        with self._lock:
            self._error = None

    def is_stale(
        self,
        now: datetime | None = None,
    ) -> bool:
        current_time = now or datetime.now()

        with self._lock:
            if self._last_message_at is None:
                return True

            return (
                current_time - self._last_message_at
                > self._stale_after
            )

    def state(
        self,
        now: datetime | None = None,
    ) -> FeedHealthState:
        current_time = now or datetime.now()

        with self._lock:
            if self._error is not None:
                return FeedHealthState.ERROR

            if not self._connected:
                return FeedHealthState.DISCONNECTED

            if self._last_message_at is None:
                return FeedHealthState.STALE

            if (
                current_time - self._last_message_at
                > self._stale_after
            ):
                return FeedHealthState.STALE

            return FeedHealthState.HEALTHY

    def snapshot(
        self,
        now: datetime | None = None,
    ) -> FeedHealthSnapshot:
        with self._lock:
            return FeedHealthSnapshot(
                state=self.state(now),
                last_message_at=self._last_message_at,
                messages_received=self._messages_received,
                reconnect_count=self._reconnect_count,
                stale_after_seconds=self._stale_after_seconds,
                error=self._error,
            )