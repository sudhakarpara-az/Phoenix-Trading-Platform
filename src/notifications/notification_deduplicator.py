"""
Bounded RuntimeEvent notification deduplication.

Phoenix does not use time-window suppression for trade alerts.
Two legitimate fills/exits occurring close together must remain
distinct.

The duplicate identity is therefore the immutable RuntimeEvent
event_id only.
"""

from __future__ import annotations

from collections import deque
from threading import RLock


class NotificationEventDeduplicator:
    """
    Bounded thread-safe event-ID claim registry.

    A claimed ID may be released when notification dispatch
    fails, allowing a later replay to retry delivery.
    """

    def __init__(
        self,
        *,
        capacity: int = 4096,
    ) -> None:
        if (
            type(capacity) is not int
            or capacity <= 0
        ):
            raise ValueError(
                "capacity must be a positive integer"
            )

        self._capacity = capacity

        self._ids: set[str] = set()

        self._order: deque[
            str
        ] = deque()

        self._lock = RLock()

    @property
    def capacity(
        self,
    ) -> int:
        return self._capacity

    @property
    def count(
        self,
    ) -> int:
        with self._lock:
            return len(
                self._ids
            )

    def claim(
        self,
        event_id: str,
    ) -> bool:
        normalized = self._normalize(
            event_id
        )

        with self._lock:
            if normalized in self._ids:
                return False

            self._ids.add(
                normalized
            )

            self._order.append(
                normalized
            )

            while (
                len(
                    self._order
                )
                > self._capacity
            ):
                oldest = (
                    self._order.popleft()
                )

                self._ids.discard(
                    oldest
                )

            return True

    def release(
        self,
        event_id: str,
    ) -> bool:
        normalized = self._normalize(
            event_id
        )

        with self._lock:
            if normalized not in self._ids:
                return False

            self._ids.remove(
                normalized
            )

            try:
                self._order.remove(
                    normalized
                )

            except ValueError:
                pass

            return True

    def contains(
        self,
        event_id: str,
    ) -> bool:
        normalized = self._normalize(
            event_id
        )

        with self._lock:
            return (
                normalized
                in self._ids
            )

    @staticmethod
    def _normalize(
        event_id: str,
    ) -> str:
        if not isinstance(
            event_id,
            str,
        ):
            raise TypeError(
                "event_id must be str"
            )

        normalized = event_id.strip()

        if not normalized:
            raise ValueError(
                "event_id cannot be empty"
            )

        return normalized


__all__ = [
    "NotificationEventDeduplicator",
]
