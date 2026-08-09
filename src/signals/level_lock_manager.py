"""
Thread-safe KS Phoenix contract + entry-level lock manager.

Prevents multiple active trades from being created for the same
selected option contract and K5/K6/K7 level combination.

This module tracks strategy lock state only.
It does not manage broker positions or orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from threading import RLock

from src.strategy.strategy_types import EntryLevel


@dataclass(frozen=True, slots=True)
class LevelLockKey:
    """
    Stable identity for one contract-specific entry-level lock.
    """

    instrument_security_id: str
    level: EntryLevel

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class LevelLock:
    """
    Represents one active contract-specific level lock.
    """

    trading_date: date
    instrument_security_id: str
    level: EntryLevel

    locked_at: datetime
    reference_id: str | None = None

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )


class LevelLockManager:
    """
    Maintains active locks by:

        instrument_security_id + EntryLevel

    Rules:
        - One active lock per contract + entry level.
        - Same K level on different contracts is independent.
        - Duplicate lock attempts for the same key are rejected.
        - Unlocking allows future re-entry for that key.
        - Locks are trading-date aware.
        - Thread-safe for concurrent signal processing.
    """

    def __init__(self) -> None:
        self._locks: dict[
            LevelLockKey,
            LevelLock,
        ] = {}

        self._trading_date: date | None = None
        self._lock = RLock()

    @property
    def trading_date(self) -> date | None:
        with self._lock:
            return self._trading_date

    def is_locked(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> bool:
        """
        Return True when the contract + level has an active lock.
        """

        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            return key in self._locks

    def acquire(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
        trading_date: date,
        locked_at: datetime,
        reference_id: str | None = None,
    ) -> bool:
        """
        Attempt to lock one contract + KS entry level.

        Returns:
            True  -> lock acquired
            False -> same contract + level already locked
        """

        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            self._ensure_trading_date(
                trading_date
            )

            if key in self._locks:
                return False

            normalized_reference_id = (
                reference_id.strip()
                if reference_id is not None
                else None
            )

            if (
                reference_id is not None
                and not normalized_reference_id
            ):
                raise ValueError(
                    "reference_id cannot be empty"
                )

            self._locks[key] = LevelLock(
                trading_date=trading_date,
                instrument_security_id=(
                    key.instrument_security_id
                ),
                level=level,
                locked_at=locked_at,
                reference_id=normalized_reference_id,
            )

            return True

    def release(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> bool:
        """
        Release one contract-specific level lock.
        """

        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            return (
                self._locks.pop(
                    key,
                    None,
                )
                is not None
            )

    def get_lock(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> LevelLock | None:
        """
        Return the active lock for one contract + level.
        """

        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            return self._locks.get(
                key
            )

    def active_levels(
        self,
        *,
        instrument_security_id: str | None = None,
    ) -> tuple[EntryLevel, ...]:
        """
        Return locked entry levels.

        When instrument_security_id is supplied, return levels
        belonging only to that contract.

        Without a contract filter, return the level associated with
        every active lock. Duplicate level values may therefore appear
        when different contracts independently own the same K level.
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
            return tuple(
                key.level
                for key in self._locks
                if (
                    normalized_security_id is None
                    or key.instrument_security_id
                    == normalized_security_id
                )
            )

    def count(self) -> int:
        """
        Return number of active contract + level locks.
        """

        with self._lock:
            return len(
                self._locks
            )

    def clear(self) -> None:
        """
        Remove all active locks.

        Intended for controlled session reset only.
        """

        with self._lock:
            self._locks.clear()
            self._trading_date = None

    @staticmethod
    def _make_key(
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> LevelLockKey:
        return LevelLockKey(
            instrument_security_id=(
                instrument_security_id.strip()
            ),
            level=level,
        )

    def _ensure_trading_date(
        self,
        trading_date: date,
    ) -> None:
        """
        Initialize or validate the active trading date.

        Existing locks are never silently discarded when the
        trading date changes.
        """

        if self._trading_date is None:
            self._trading_date = trading_date
            return

        if self._trading_date == trading_date:
            return

        if self._locks:
            raise RuntimeError(
                "cannot change trading date while level locks are active"
            )

        self._trading_date = trading_date
