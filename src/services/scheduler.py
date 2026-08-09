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

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


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
    Raised when a future scheduler implementation attempts an
    illegal trading-day lifecycle transition.
    """


__all__ = [
    "TradingCalendar",
    "TradingDaySnapshot",
    "TradingDayState",
    "TradingDayTransitionError",
]
