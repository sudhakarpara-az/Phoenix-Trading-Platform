"""
Phoenix M10 trading-day scheduler domain contracts.

This module defines the application-level trading-day lifecycle
owned by M10.

It does not replace:

    - M08 RuntimeState / TradingRuntimeOrchestrator
    - M03 StrategySessionState / TradingSessionManager
    - M07 force-exit mechanics
    - M05 option selection
    - M02 market-data handling

M10 coordinates those existing boundaries across one trading day.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum
from threading import RLock


class TradingDayState(str, Enum):
    """
    M10 orchestration state for one Phoenix trading day.

    The state describes scheduler progress only. Runtime health and
    strategy-instrument state remain owned by their existing modules.
    """

    CREATED = "CREATED"

    NON_TRADING_DAY = "NON_TRADING_DAY"

    WAITING_FOR_MARKET = "WAITING_FOR_MARKET"

    WAITING_FOR_REFERENCE_CLOSE = (
        "WAITING_FOR_REFERENCE_CLOSE"
    )

    SELECTING_OPTIONS = "SELECTING_OPTIONS"

    PREPARING_LEVELS = "PREPARING_LEVELS"

    WAITING_FOR_MONITORING = (
        "WAITING_FOR_MONITORING"
    )

    MONITORING = "MONITORING"

    EXIT_ONLY = "EXIT_ONLY"

    CLOSED = "CLOSED"

    FAILED = "FAILED"


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDaySnapshot:
    """
    Immutable point-in-time M10 trading-day scheduler state.

    This contract intentionally contains no broker credentials,
    option-chain payloads, KS calculations, orders, or positions.
    Those remain owned by their respective modules.
    """

    trading_date: date
    state: TradingDayState
    updated_at: datetime

    started_at: datetime | None = None
    closed_at: datetime | None = None

    failure_message: str | None = None

    def __post_init__(self) -> None:
        if (
            self.started_at is not None
            and self.updated_at < self.started_at
        ):
            raise ValueError(
                "updated_at cannot be before started_at"
            )

        if self.closed_at is not None:
            if self.started_at is None:
                raise ValueError(
                    "closed trading day requires started_at"
                )

            if self.closed_at < self.started_at:
                raise ValueError(
                    "closed_at cannot be before started_at"
                )

            if self.updated_at < self.closed_at:
                raise ValueError(
                    "updated_at cannot be before closed_at"
                )

        if (
            self.state is TradingDayState.CREATED
            and self.started_at is not None
        ):
            raise ValueError(
                "CREATED trading day cannot have started_at"
            )

        if (
            self.state is TradingDayState.CREATED
            and self.closed_at is not None
        ):
            raise ValueError(
                "CREATED trading day cannot have closed_at"
            )

        terminal_states = {
            TradingDayState.NON_TRADING_DAY,
            TradingDayState.CLOSED,
        }

        if (
            self.state in terminal_states
            and self.closed_at is None
        ):
            raise ValueError(
                f"{self.state.value} trading day requires "
                "closed_at"
            )

        if (
            self.state not in terminal_states
            and self.closed_at is not None
        ):
            raise ValueError(
                "only terminal trading-day states may have "
                "closed_at"
            )

        normalized_failure = (
            self.failure_message.strip()
            if self.failure_message is not None
            else None
        )

        if self.state is TradingDayState.FAILED:
            if not normalized_failure:
                raise ValueError(
                    "FAILED trading day requires "
                    "failure_message"
                )
        elif self.failure_message is not None:
            raise ValueError(
                "failure_message is only valid for "
                "FAILED state"
            )

        if (
            normalized_failure is not None
            and normalized_failure
            != self.failure_message
        ):
            object.__setattr__(
                self,
                "failure_message",
                normalized_failure,
            )

    @property
    def is_terminal(self) -> bool:
        return self.state in {
            TradingDayState.NON_TRADING_DAY,
            TradingDayState.CLOSED,
            TradingDayState.FAILED,
        }

    @property
    def can_accept_new_entries(self) -> bool:
        """
        M10 scheduler-level entry gate.

        Runtime, account, signal, execution, position and risk gates
        are evaluated separately.
        """

        return self.state is TradingDayState.MONITORING

    @property
    def can_manage_positions(self) -> bool:
        """
        Position management remains available while monitoring and
        during the mandatory exit-only phase.
        """

        return self.state in {
            TradingDayState.MONITORING,
            TradingDayState.EXIT_ONLY,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class TradingCalendar:
    """
    Deterministic M10 trading-day eligibility calendar.

    Phoenix treats Monday-Friday as candidate trading days.
    Exchange holidays are supplied explicitly by the application
    boundary rather than hardcoded into strategy/runtime logic.

    This keeps M10 deterministic in tests while allowing a future
    NSE calendar adapter or configuration source to provide the
    authoritative holiday set.
    """

    holidays: frozenset[date] = frozenset()

    def __post_init__(self) -> None:
        normalized: set[date] = set()

        for holiday in self.holidays:
            if type(holiday) is not date:
                raise TypeError(
                    "trading calendar holidays must contain "
                    "date values"
                )

            normalized.add(holiday)

        object.__setattr__(
            self,
            "holidays",
            frozenset(normalized),
        )

    def is_weekend(
        self,
        trading_date: date,
    ) -> bool:
        self._validate_trading_date(
            trading_date
        )

        return trading_date.weekday() >= 5

    def is_holiday(
        self,
        trading_date: date,
    ) -> bool:
        self._validate_trading_date(
            trading_date
        )

        return trading_date in self.holidays

    def is_trading_day(
        self,
        trading_date: date,
    ) -> bool:
        """
        Return True only for an eligible market trading date.
        """

        self._validate_trading_date(
            trading_date
        )

        return (
            trading_date.weekday() < 5
            and trading_date not in self.holidays
        )

    @staticmethod
    def _validate_trading_date(
        trading_date: date,
    ) -> None:
        if type(trading_date) is not date:
            raise TypeError(
                "trading_date must be a date"
            )


class TradingDayTransitionError(RuntimeError):
    """
    Raised when M10 attempts an illegal trading-day transition.
    """


class TradingDayScheduler:
    """
    Stateful M10 trading-day lifecycle coordinator.

    This class owns only trading-day orchestration state.

    It does not calculate strategy levels, select options,
    process market data, execute orders, or replace the M03
    TradingSessionManager.

    Normal trading-day progression:

        CREATED
          -> WAITING_FOR_MARKET
          -> WAITING_FOR_REFERENCE_CLOSE
          -> SELECTING_OPTIONS
          -> PREPARING_LEVELS
          -> WAITING_FOR_MONITORING
          -> MONITORING
          -> EXIT_ONLY
          -> CLOSED

    Force-exit processing may move any active market-day state
    directly into EXIT_ONLY. This ensures the 15:15 safety
    boundary is not blocked by an incomplete morning milestone.
    """

    _TRANSITIONS: dict[
        TradingDayState,
        frozenset[TradingDayState],
    ] = {
        TradingDayState.WAITING_FOR_MARKET: frozenset(
            {
                TradingDayState.WAITING_FOR_REFERENCE_CLOSE,
                TradingDayState.EXIT_ONLY,
            }
        ),
        TradingDayState.WAITING_FOR_REFERENCE_CLOSE: frozenset(
            {
                TradingDayState.SELECTING_OPTIONS,
                TradingDayState.EXIT_ONLY,
            }
        ),
        TradingDayState.SELECTING_OPTIONS: frozenset(
            {
                TradingDayState.PREPARING_LEVELS,
                TradingDayState.EXIT_ONLY,
            }
        ),
        TradingDayState.PREPARING_LEVELS: frozenset(
            {
                TradingDayState.WAITING_FOR_MONITORING,
                TradingDayState.EXIT_ONLY,
            }
        ),
        TradingDayState.WAITING_FOR_MONITORING: frozenset(
            {
                TradingDayState.MONITORING,
                TradingDayState.EXIT_ONLY,
            }
        ),
        TradingDayState.MONITORING: frozenset(
            {
                TradingDayState.EXIT_ONLY,
            }
        ),
        TradingDayState.EXIT_ONLY: frozenset(
            {
                TradingDayState.CLOSED,
            }
        ),
    }

    def __init__(
        self,
        *,
        trading_date: date,
        created_at: datetime,
        calendar: TradingCalendar | None = None,
    ) -> None:
        if type(trading_date) is not date:
            raise TypeError(
                "trading_date must be a date"
            )

        if type(created_at) is not datetime:
            raise TypeError(
                "created_at must be a datetime"
            )

        self._calendar = (
            calendar
            if calendar is not None
            else TradingCalendar()
        )

        self._snapshot = TradingDaySnapshot(
            trading_date=trading_date,
            state=TradingDayState.CREATED,
            updated_at=created_at,
        )

        self._lock = RLock()

    @property
    def snapshot(self) -> TradingDaySnapshot:
        with self._lock:
            return self._snapshot

    @property
    def state(self) -> TradingDayState:
        return self.snapshot.state

    @property
    def trading_date(self) -> date:
        return self.snapshot.trading_date

    @property
    def calendar(self) -> TradingCalendar:
        return self._calendar

    def start(
        self,
        *,
        started_at: datetime,
    ) -> TradingDaySnapshot:
        """
        Evaluate calendar eligibility and start the trading day.

        Trading date:
            CREATED -> WAITING_FOR_MARKET

        Weekend / explicit holiday:
            CREATED -> NON_TRADING_DAY
        """

        self._validate_timestamp(
            started_at,
            name="started_at",
        )

        with self._lock:
            if (
                self._snapshot.state
                is not TradingDayState.CREATED
            ):
                raise TradingDayTransitionError(
                    "trading day can only start from CREATED"
                )

            self._validate_monotonic_timestamp(
                started_at
            )

            if not self._calendar.is_trading_day(
                self._snapshot.trading_date
            ):
                self._snapshot = replace(
                    self._snapshot,
                    state=TradingDayState.NON_TRADING_DAY,
                    started_at=started_at,
                    closed_at=started_at,
                    updated_at=started_at,
                )

                return self._snapshot

            self._snapshot = replace(
                self._snapshot,
                state=TradingDayState.WAITING_FOR_MARKET,
                started_at=started_at,
                updated_at=started_at,
            )

            return self._snapshot

    def can_transition_to(
        self,
        target_state: TradingDayState,
    ) -> bool:
        if not isinstance(
            target_state,
            TradingDayState,
        ):
            raise TypeError(
                "target_state must be TradingDayState"
            )

        with self._lock:
            return target_state in self._TRANSITIONS.get(
                self._snapshot.state,
                frozenset(),
            )

    def transition(
        self,
        *,
        target_state: TradingDayState,
        transitioned_at: datetime,
    ) -> TradingDaySnapshot:
        """
        Perform one explicit legal M10 lifecycle transition.

        Time-driven decisions are intentionally not made here.
        Later M10 tasks decide when each transition is due.
        """

        if not isinstance(
            target_state,
            TradingDayState,
        ):
            raise TypeError(
                "target_state must be TradingDayState"
            )

        self._validate_timestamp(
            transitioned_at,
            name="transitioned_at",
        )

        with self._lock:
            current_state = self._snapshot.state

            allowed = self._TRANSITIONS.get(
                current_state,
                frozenset(),
            )

            if target_state not in allowed:
                raise TradingDayTransitionError(
                    "illegal trading-day transition: "
                    f"{current_state.value} -> "
                    f"{target_state.value}"
                )

            self._validate_monotonic_timestamp(
                transitioned_at
            )

            if target_state is TradingDayState.CLOSED:
                self._snapshot = replace(
                    self._snapshot,
                    state=target_state,
                    closed_at=transitioned_at,
                    updated_at=transitioned_at,
                )
            else:
                self._snapshot = replace(
                    self._snapshot,
                    state=target_state,
                    updated_at=transitioned_at,
                )

            return self._snapshot

    def fail(
        self,
        *,
        message: str,
        failed_at: datetime,
    ) -> TradingDaySnapshot:
        """
        Move a non-terminal trading day into FAILED.

        Operational broker/position failures do not automatically
        belong here; M08/M07 retain ownership of their own failure
        handling. This method is for fatal M10 scheduler failures.
        """

        normalized_message = message.strip()

        if not normalized_message:
            raise ValueError(
                "failure message cannot be empty"
            )

        self._validate_timestamp(
            failed_at,
            name="failed_at",
        )

        with self._lock:
            if self._snapshot.is_terminal:
                raise TradingDayTransitionError(
                    "terminal trading day cannot fail"
                )

            self._validate_monotonic_timestamp(
                failed_at
            )

            self._snapshot = replace(
                self._snapshot,
                state=TradingDayState.FAILED,
                updated_at=failed_at,
                failure_message=normalized_message,
            )

            return self._snapshot

    def _validate_monotonic_timestamp(
        self,
        timestamp: datetime,
    ) -> None:
        if timestamp < self._snapshot.updated_at:
            raise TradingDayTransitionError(
                "trading-day transition timestamp cannot "
                "move backwards"
            )

    @staticmethod
    def _validate_timestamp(
        timestamp: datetime,
        *,
        name: str,
    ) -> None:
        if type(timestamp) is not datetime:
            raise TypeError(
                f"{name} must be a datetime"
            )


__all__ = [
    "TradingCalendar",
    "TradingDayScheduler",
    "TradingDaySnapshot",
    "TradingDayState",
    "TradingDayTransitionError",
]
