"""
Duplicate signal suppression for Phoenix Trading Platform.

Prevents repeated LevelEvent objects from generating
multiple identical trading signals within a short time window.

Duplicate identity is contract-aware:
    instrument_security_id + KS level + event type

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
    Identifies one unique signal candidate for one contract.
    """

    instrument_security_id: str
    level: KSLevelName
    event_type: LevelEventType

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )


class DuplicateSignalGuard:
    """
    Suppresses repeated signal candidates within a configured window.

    Events are independent across selected option contracts.

    Example:
        CE contract K5 CROSSED_UP at 10:00:00
        CE contract K5 CROSSED_UP at 10:00:01

    The second CE event is suppressed inside the configured window.

    A PE contract at K5 is a different fingerprint and is evaluated
    independently.
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
        Return True when the contract-specific event is not a duplicate.

        Accepted events update the fingerprint timestamp.
        """

        fingerprint = SignalFingerprint(
            instrument_security_id=(
                event.instrument_security_id
            ),
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
        *,
        instrument_security_id: str | None = None,
    ) -> None:
        """
        Remove duplicate history for one KS level.

        When instrument_security_id is supplied, only that contract
        and level are cleared.

        Omitting instrument_security_id preserves the legacy
        session-reset behavior and clears all contracts at the level.
        """

        normalized_security_id = None

        if instrument_security_id is not None:
            normalized_security_id = (
                instrument_security_id.strip()
            )

            if not normalized_security_id:
                raise ValueError(
                    "instrument_security_id cannot be empty"
                )

        with self._lock:
            keys = [
                fingerprint
                for fingerprint in self._last_seen
                if (
                    fingerprint.level is level
                    and (
                        normalized_security_id is None
                        or fingerprint.instrument_security_id
                        == normalized_security_id
                    )
                )
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
