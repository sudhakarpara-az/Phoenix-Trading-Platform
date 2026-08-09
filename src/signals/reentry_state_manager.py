"""
Contract-aware re-entry state tracking for Phoenix Trading Platform.

Tracks whether each selected option contract + KS entry level has
already traded during the current trading session and whether a future
eligible signal should be treated as a re-entry.

Identity:
    instrument_security_id + EntryLevel

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
    Lifecycle status for one contract + KS entry level.
    """

    NEVER_TRADED = "NEVER_TRADED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class ReentryStateKey:
    """
    Stable identity for one contract-specific re-entry state.
    """

    instrument_security_id: str
    level: EntryLevel

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class ReentryState:
    """
    Current re-entry state for one contract + KS level.
    """

    trading_date: date
    instrument_security_id: str
    level: EntryLevel

    status: ReentryStatus
    trade_count: int

    last_opened_at: datetime | None = None
    last_closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )


class ReentryStateManager:
    """
    Tracks trading history by:

        instrument_security_id + EntryLevel

    Rules:
        - First trade for a contract + level is not re-entry.
        - Same K level on different contracts is independent.
        - A contract + level cannot re-enter while ACTIVE.
        - After CLOSED, its next valid trade is a re-entry.
        - Trade count increments whenever a new trade starts.
        - State is trading-date aware.
    """

    def __init__(self) -> None:
        self._states: dict[
            ReentryStateKey,
            ReentryState,
        ] = {}

        self._trading_date: date | None = None
        self._lock = RLock()

    @property
    def trading_date(self) -> date | None:
        with self._lock:
            return self._trading_date

    def get_state(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> ReentryState | None:
        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            return self._states.get(
                key
            )

    def can_enter(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> bool:
        """
        Return True when this contract + level can start a trade.
        """

        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            state = self._states.get(
                key
            )

            if state is None:
                return True

            return (
                state.status
                is not ReentryStatus.ACTIVE
            )

    def is_reentry(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> bool:
        """
        Return True when the next allowed trade for this contract
        + level should be classified as re-entry.
        """

        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            state = self._states.get(
                key
            )

            if state is None:
                return False

            return (
                state.status
                is ReentryStatus.CLOSED
                and state.trade_count >= 1
            )

    def mark_open(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
        trading_date: date,
        opened_at: datetime,
    ) -> ReentryState:
        """
        Mark one contract + level trade as active.

        Raises RuntimeError when the same contract + level
        is already ACTIVE.
        """

        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            self._ensure_trading_date(
                trading_date
            )

            current = self._states.get(
                key
            )

            if (
                current is not None
                and current.status
                is ReentryStatus.ACTIVE
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
                instrument_security_id=(
                    key.instrument_security_id
                ),
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

            self._states[key] = new_state

            return new_state

    def mark_closed(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
        closed_at: datetime,
    ) -> ReentryState:
        """
        Mark the active contract + level trade as closed.
        """

        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            current = self._states.get(
                key
            )

            if current is None:
                raise RuntimeError(
                    f"{level.value} has no trade history"
                )

            if (
                current.status
                is not ReentryStatus.ACTIVE
            ):
                raise RuntimeError(
                    f"{level.value} does not have an active trade"
                )

            new_state = ReentryState(
                trading_date=current.trading_date,
                instrument_security_id=(
                    current.instrument_security_id
                ),
                level=level,
                status=ReentryStatus.CLOSED,
                trade_count=current.trade_count,
                last_opened_at=current.last_opened_at,
                last_closed_at=closed_at,
            )

            self._states[key] = new_state

            return new_state

    def trade_count(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> int:
        key = self._make_key(
            instrument_security_id=instrument_security_id,
            level=level,
        )

        with self._lock:
            state = self._states.get(
                key
            )

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

    @staticmethod
    def _make_key(
        *,
        instrument_security_id: str,
        level: EntryLevel,
    ) -> ReentryStateKey:
        return ReentryStateKey(
            instrument_security_id=(
                instrument_security_id.strip()
            ),
            level=level,
        )

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
