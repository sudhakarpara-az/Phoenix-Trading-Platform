"""
Duplicate signal suppression for Phoenix Trading Platform.

Prevents repeated LevelEvent objects from generating
multiple identical trading signals within a short time window.

This module does not manage active positions or level locks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock

from src.strategy.strategy_types import (
    KSLevelName,
    LevelEvent,
    LevelEventType,
)


@dataclass(frozen=True, slots=True)
class SignalFingerprint:
    """
    Identifies one unique signal candidate.
    """

    level: KSLevelName
    event_type: LevelEventType


class DuplicateSignalGuard:
    """
    Suppresses repeated signal candidates within a configured window.

    Example:
        K5 CROSSED_UP at 10:00:00
        K5 CROSSED_UP at 10:00:01
        K5 CROSSED_UP at 10:00:02

    Only the first event is accepted when the suppression
    window is 5 seconds.
    """

    def __init__(
        self,
        suppression_seconds: float = 5.0,
    ) -> None:
        if suppression_seconds <= 0:
            raise ValueError(
                "suppression_seconds must be greater than zero"
            )

        self._window = timedelta(
            seconds=suppression_seconds
        )

        self._last_seen: dict[
            SignalFingerprint,
            datetime,
        ] = {}

        self._lock = RLock()

    def allow(
        self,
        event: LevelEvent,
    ) -> bool:
        """
        Return True when the event is not a duplicate.

        Accepted events update the fingerprint timestamp.
        """

        fingerprint = SignalFingerprint(
            level=event.level,
            event_type=event.event_type,
        )

        with self._lock:
            previous_time = self._last_seen.get(
                fingerprint
            )

            if previous_time is None:
                self._last_seen[fingerprint] = (
                    event.timestamp
                )

                return True

            if (
                event.timestamp - previous_time
                >= self._window
            ):
                self._last_seen[fingerprint] = (
                    event.timestamp
                )

                return True

            return False

    def clear_level(
        self,
        level: KSLevelName,
    ) -> None:
        """
        Remove duplicate history for one KS level.

        Useful when the previous trade has fully closed
        and re-entry should be evaluated fresh.
        """

        with self._lock:
            keys = [
                fingerprint
                for fingerprint in self._last_seen
                if fingerprint.level is level
            ]

            for fingerprint in keys:
                del self._last_seen[fingerprint]

    def clear(self) -> None:
        """
        Clear all duplicate history.
        """

        with self._lock:
            self._last_seen.clear()

    def count(self) -> int:
        """
        Return number of stored fingerprints.
        """

        with self._lock:
            return len(self._last_seen)