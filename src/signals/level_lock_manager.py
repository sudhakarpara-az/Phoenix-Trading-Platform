"""
Thread-safe KS Phoenix entry-level lock manager.

Prevents multiple active trades from being created
for the same K5/K6/K7 level.

This module tracks strategy-level lock state only.
It does not manage broker positions or orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from threading import RLock

from src.strategy.strategy_types import EntryLevel


@dataclass(frozen=True, slots=True)
class LevelLock:
    """
    Represents one active level lock.
    """

    trading_date: date
    level: EntryLevel

    locked_at: datetime
    reference_id: str | None = None


class LevelLockManager:
    """
    Maintains active locks for K5/K6/K7.

    Rules:
        - One active lock per entry level.
        - Duplicate lock attempts are rejected.
        - Unlocking allows future re-entry.
        - Locks are trading-date aware.
        - Thread-safe for future concurrent signal processing.
    """

    def __init__(self) -> None:
        self._locks: dict[EntryLevel, LevelLock] = {}
        self._trading_date: date | None = None
        self._lock = RLock()

    @property
    def trading_date(self) -> date | None:
        with self._lock:
            return self._trading_date

    def is_locked(
        self,
        level: EntryLevel,
    ) -> bool:
        """
        Return True when the entry level currently has
        an active lock.
        """

        with self._lock:
            return level in self._locks

    def acquire(
        self,
        level: EntryLevel,
        trading_date: date,
        locked_at: datetime,
        reference_id: str | None = None,
    ) -> bool:
        """
        Attempt to lock one KS entry level.

        Returns:
            True  -> lock acquired
            False -> level was already locked
        """

        with self._lock:
            self._ensure_trading_date(trading_date)

            if level in self._locks:
                return False

            normalized_reference_id = (
                reference_id.strip()
                if reference_id is not None
                else None
            )

            if reference_id is not None and not normalized_reference_id:
                raise ValueError(
                    "reference_id cannot be empty"
                )

            self._locks[level] = LevelLock(
                trading_date=trading_date,
                level=level,
                locked_at=locked_at,
                reference_id=normalized_reference_id,
            )

            return True

    def release(
        self,
        level: EntryLevel,
    ) -> bool:
        """
        Release an active level lock.

        Returns:
            True  -> lock existed and was released
            False -> level was already unlocked
        """

        with self._lock:
            return self._locks.pop(level, None) is not None

    def get_lock(
        self,
        level: EntryLevel,
    ) -> LevelLock | None:
        """
        Return the active lock for a level.
        """

        with self._lock:
            return self._locks.get(level)

    def active_levels(
        self,
    ) -> tuple[EntryLevel, ...]:
        """
        Return all currently locked entry levels.
        """

        with self._lock:
            return tuple(self._locks.keys())

    def count(self) -> int:
        """
        Return number of active level locks.
        """

        with self._lock:
            return len(self._locks)

    def clear(self) -> None:
        """
        Remove all active locks.

        Intended for controlled session reset only.
        """

        with self._lock:
            self._locks.clear()
            self._trading_date = None

    def _ensure_trading_date(
        self,
        trading_date: date,
    ) -> None:
        """
        Initialize or validate the active trading date.

        We deliberately do not auto-clear existing locks
        if the date changes while locks are active.
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