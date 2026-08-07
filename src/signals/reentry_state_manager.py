"""
Re-entry state tracking for Phoenix Trading Platform.

Tracks whether each KS entry level has already traded
during the current trading session and whether a future
eligible signal should be treated as a re-entry.

This module does not place orders or manage broker positions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from threading import RLock

from src.strategy.strategy_types import EntryLevel


class ReentryStatus(str, Enum):
    """
    Lifecycle status for one KS entry level.
    """

    NEVER_TRADED = "NEVER_TRADED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class ReentryState:
    """
    Current re-entry state for one KS level.
    """

    trading_date: date
    level: EntryLevel
    status: ReentryStatus
    trade_count: int
    last_opened_at: datetime | None = None
    last_closed_at: datetime | None = None


class ReentryStateManager:
    """
    Tracks trading history for K5/K6/K7 within one trading session.

    Rules:
        - First trade is not re-entry.
        - A level cannot re-enter while ACTIVE.
        - After CLOSED, the next valid trade is a re-entry.
        - Trade count increments whenever a new trade starts.
        - State is trading-date aware.
    """

    def __init__(self) -> None:
        self._states: dict[EntryLevel, ReentryState] = {}
        self._trading_date: date | None = None
        self._lock = RLock()

    @property
    def trading_date(self) -> date | None:
        with self._lock:
            return self._trading_date

    def get_state(
        self,
        level: EntryLevel,
    ) -> ReentryState | None:
        with self._lock:
            return self._states.get(level)

    def can_enter(
        self,
        level: EntryLevel,
    ) -> bool:
        """
        Return True when a new trade is currently allowed.
        """

        with self._lock:
            state = self._states.get(level)

            if state is None:
                return True

            return state.status is not ReentryStatus.ACTIVE

    def is_reentry(
        self,
        level: EntryLevel,
    ) -> bool:
        """
        Return True when the next allowed trade should
        be treated as a re-entry.
        """

        with self._lock:
            state = self._states.get(level)

            if state is None:
                return False

            return (
                state.status is ReentryStatus.CLOSED
                and state.trade_count >= 1
            )

    def mark_open(
        self,
        level: EntryLevel,
        trading_date: date,
        opened_at: datetime,
    ) -> ReentryState:
        """
        Mark a new trade as active.

        Raises RuntimeError when the level is already ACTIVE.
        """

        with self._lock:
            self._ensure_trading_date(trading_date)

            current = self._states.get(level)

            if (
                current is not None
                and current.status is ReentryStatus.ACTIVE
            ):
                raise RuntimeError(
                    f"{level.value} already has an active trade"
                )

            trade_count = (
                1
                if current is None
                else current.trade_count + 1
            )

            new_state = ReentryState(
                trading_date=trading_date,
                level=level,
                status=ReentryStatus.ACTIVE,
                trade_count=trade_count,
                last_opened_at=opened_at,
                last_closed_at=(
                    current.last_closed_at
                    if current is not None
                    else None
                ),
            )

            self._states[level] = new_state

            return new_state

    def mark_closed(
        self,
        level: EntryLevel,
        closed_at: datetime,
    ) -> ReentryState:
        """
        Mark the currently active trade as closed.

        Raises RuntimeError if the level has never traded
        or is not currently ACTIVE.
        """

        with self._lock:
            current = self._states.get(level)

            if current is None:
                raise RuntimeError(
                    f"{level.value} has no trade history"
                )

            if current.status is not ReentryStatus.ACTIVE:
                raise RuntimeError(
                    f"{level.value} does not have an active trade"
                )

            new_state = ReentryState(
                trading_date=current.trading_date,
                level=level,
                status=ReentryStatus.CLOSED,
                trade_count=current.trade_count,
                last_opened_at=current.last_opened_at,
                last_closed_at=closed_at,
            )

            self._states[level] = new_state

            return new_state

    def trade_count(
        self,
        level: EntryLevel,
    ) -> int:
        with self._lock:
            state = self._states.get(level)

            if state is None:
                return 0

            return state.trade_count

    def reset(self) -> None:
        """
        Clear the entire session re-entry state.
        """

        with self._lock:
            self._states.clear()
            self._trading_date = None

    def _ensure_trading_date(
        self,
        trading_date: date,
    ) -> None:
        if self._trading_date is None:
            self._trading_date = trading_date
            return

        if self._trading_date == trading_date:
            return

        if any(
            state.status is ReentryStatus.ACTIVE
            for state in self._states.values()
        ):
            raise RuntimeError(
                "cannot change trading date while trades are active"
            )

        self._states.clear()
        self._trading_date = trading_date