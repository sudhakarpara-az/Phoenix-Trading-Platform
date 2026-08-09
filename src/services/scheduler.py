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
from datetime import date, datetime, time
from enum import Enum
from math import isfinite
from threading import RLock
from typing import Protocol

from src.option_selection.option_types import (
    OptionSelectionResult,
    OptionSelectionStatus,
    OptionType,
    SelectedOption,
)
from src.runtime.recovery_types import (
    StartupRecoveryPlan,
    StartupRecoveryResult,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeSnapshot,
    RuntimeState,
)


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


@dataclass(
    frozen=True,
    slots=True,
)
class ReferenceWindowSchedule:
    """
    M10 schedule for the Phoenix 09:15 reference window.

    This contract owns only the reference-window boundaries.
    Monitoring activation and force-exit timing remain separate
    M10 tasks.
    """

    market_open: time = time(9, 15)
    reference_candle_end: time = time(9, 16)

    def __post_init__(self) -> None:
        if type(self.market_open) is not time:
            raise TypeError(
                "market_open must be a time"
            )

        if type(self.reference_candle_end) is not time:
            raise TypeError(
                "reference_candle_end must be a time"
            )

        if (
            self.reference_candle_end
            <= self.market_open
        ):
            raise ValueError(
                "reference_candle_end must be after "
                "market_open"
            )


class TradingDayReferenceCoordinator:
    """
    Coordinates only the M10 09:15-09:16 reference boundary.

    It does not build a ReferenceCandle and does not select an
    option contract.

    The final selected CE/PE contracts are not known until the
    next M10 selection phase. T07 therefore owns proving and
    loading each selected contract's completed reference candle.

    State ownership:

        WAITING_FOR_MARKET
            ->
        WAITING_FOR_REFERENCE_CLOSE

    T06 owns the later transition to SELECTING_OPTIONS.
    """

    def __init__(
        self,
        *,
        scheduler: TradingDayScheduler,
        schedule: ReferenceWindowSchedule | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._schedule = (
            schedule
            if schedule is not None
            else ReferenceWindowSchedule()
        )

    @property
    def scheduler(self) -> TradingDayScheduler:
        return self._scheduler

    @property
    def schedule(self) -> ReferenceWindowSchedule:
        return self._schedule

    def is_reference_window_open(
        self,
        now: datetime,
    ) -> bool:
        self._validate_datetime(
            now
        )

        self._validate_trading_date(
            now
        )

        current_time = now.time()

        return (
            self._schedule.market_open
            <= current_time
            < self._schedule.reference_candle_end
        )

    def is_reference_window_complete(
        self,
        now: datetime,
    ) -> bool:
        self._validate_datetime(
            now
        )

        self._validate_trading_date(
            now
        )

        return (
            now.time()
            >= self._schedule.reference_candle_end
        )

    def begin_reference_window(
        self,
        *,
        opened_at: datetime,
    ) -> TradingDaySnapshot:
        """
        Enter WAITING_FOR_REFERENCE_CLOSE at or after 09:15.

        Calling again while already waiting for reference close
        is idempotent.

        A late application start may still establish this
        scheduler milestone after 09:16; T06/T07 must then prove
        that option selection and completed reference-candle data
        are available before entries can ever be enabled.
        """

        self._validate_datetime(
            opened_at
        )

        self._validate_trading_date(
            opened_at
        )

        if (
            opened_at.time()
            < self._schedule.market_open
        ):
            raise TradingDayTransitionError(
                "reference window cannot begin before "
                "market_open"
            )

        state = self._scheduler.state

        if (
            state
            is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
        ):
            return self._scheduler.snapshot

        if (
            state
            is not TradingDayState.WAITING_FOR_MARKET
        ):
            raise TradingDayTransitionError(
                "reference window can only begin from "
                "WAITING_FOR_MARKET"
            )

        return self._scheduler.transition(
            target_state=(
                TradingDayState
                .WAITING_FOR_REFERENCE_CLOSE
            ),
            transitioned_at=opened_at,
        )

    def _validate_trading_date(
        self,
        now: datetime,
    ) -> None:
        if (
            now.date()
            != self._scheduler.trading_date
        ):
            raise TradingDayTransitionError(
                "reference-window timestamp does not match "
                "scheduler trading_date"
            )

    @staticmethod
    def _validate_datetime(
        value: datetime,
    ) -> None:
        if type(value) is not datetime:
            raise TypeError(
                "reference-window timestamp must be a datetime"
            )


class MorningOptionSelectionPort(Protocol):
    """
    Narrow M10 boundary to the M05 signal-independent
    option-selection API.
    """

    def select_for_option_type(
        self,
        *,
        option_type: OptionType,
        trading_date: date,
        reference_price: float,
        requested_at: datetime,
        requested_expiry: date | None = None,
    ) -> OptionSelectionResult:
        ...


class TradingDayOptionSelectionError(RuntimeError):
    """
    Raised when M10 cannot safely accept a morning option pair.
    """


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayOptionSelectionResult:
    """
    Immutable result of one M10 CE/PE morning-selection attempt.

    The attempt is complete only when both independent M05
    requests produced valid selected contracts.
    """

    call_result: OptionSelectionResult
    put_result: OptionSelectionResult
    attempted_at: datetime
    completed_at: datetime | None = None

    @property
    def is_complete(self) -> bool:
        return (
            self.call_result.status
            is OptionSelectionStatus.SELECTED
            and self.put_result.status
            is OptionSelectionStatus.SELECTED
            and self.completed_at is not None
        )

    @property
    def selected_call(
        self,
    ) -> SelectedOption | None:
        return self.call_result.selected_option

    @property
    def selected_put(
        self,
    ) -> SelectedOption | None:
        return self.put_result.selected_option


class TradingDayOptionSelectionCoordinator:
    """
    Coordinates the M10 09:16 CE/PE selection milestone.

    Rules:
        - Selection cannot begin before the 09:15 reference
          window has closed.
        - CALL and PUT are requested independently from M05.
        - Both use the same supplied NIFTY reference price.
        - Both must succeed before M10 enters PREPARING_LEVELS.
        - A partial/failed pair remains SELECTING_OPTIONS.
        - A successful pair is immutable for this coordinator
          instance and repeated calls return that same pair.

    This coordinator does not build option reference candles or
    calculate KS levels. Those responsibilities belong to T07.
    """

    def __init__(
        self,
        *,
        scheduler: TradingDayScheduler,
        selection_service: MorningOptionSelectionPort,
        schedule: ReferenceWindowSchedule | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._selection_service = selection_service
        self._schedule = (
            schedule
            if schedule is not None
            else ReferenceWindowSchedule()
        )

        self._completed_result: (
            TradingDayOptionSelectionResult | None
        ) = None

        self._lock = RLock()

    @property
    def scheduler(self) -> TradingDayScheduler:
        return self._scheduler

    @property
    def completed_result(
        self,
    ) -> TradingDayOptionSelectionResult | None:
        with self._lock:
            return self._completed_result

    def select_options(
        self,
        *,
        reference_price: float,
        requested_at: datetime,
        requested_expiry: date | None = None,
    ) -> TradingDayOptionSelectionResult:
        """
        Independently select the morning CALL and PUT contracts.

        A failed attempt is intentionally retryable. No successful
        side is frozen independently because Phoenix requires one
        coherent morning CE/PE pair.
        """

        self._validate_datetime(
            requested_at
        )

        self._validate_trading_date(
            requested_at
        )

        self._validate_reference_price(
            reference_price
        )

        if (
            requested_at.time()
            < self._schedule.reference_candle_end
        ):
            raise TradingDayOptionSelectionError(
                "option selection cannot begin before "
                "reference_candle_end"
            )

        with self._lock:
            if self._completed_result is not None:
                self._validate_repeat_request(
                    requested_expiry=(
                        requested_expiry
                    )
                )

                return self._completed_result

            state = self._scheduler.state

            if (
                state
                is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
            ):
                self._scheduler.transition(
                    target_state=(
                        TradingDayState.SELECTING_OPTIONS
                    ),
                    transitioned_at=requested_at,
                )

            elif (
                state
                is not TradingDayState.SELECTING_OPTIONS
            ):
                raise TradingDayOptionSelectionError(
                    "option selection requires "
                    "WAITING_FOR_REFERENCE_CLOSE or "
                    "SELECTING_OPTIONS state"
                )

            call_result = (
                self._selection_service
                .select_for_option_type(
                    option_type=OptionType.CALL,
                    trading_date=(
                        self._scheduler.trading_date
                    ),
                    reference_price=reference_price,
                    requested_at=requested_at,
                    requested_expiry=requested_expiry,
                )
            )

            put_result = (
                self._selection_service
                .select_for_option_type(
                    option_type=OptionType.PUT,
                    trading_date=(
                        self._scheduler.trading_date
                    ),
                    reference_price=reference_price,
                    requested_at=requested_at,
                    requested_expiry=requested_expiry,
                )
            )

            attempt = TradingDayOptionSelectionResult(
                call_result=call_result,
                put_result=put_result,
                attempted_at=requested_at,
            )

            if not (
                call_result.status
                is OptionSelectionStatus.SELECTED
                and put_result.status
                is OptionSelectionStatus.SELECTED
            ):
                return attempt

            call_option = (
                call_result.selected_option
            )

            put_option = (
                put_result.selected_option
            )

            assert call_option is not None
            assert put_option is not None

            self._validate_selected_pair(
                call_option=call_option,
                put_option=put_option,
                requested_expiry=requested_expiry,
            )

            completed = TradingDayOptionSelectionResult(
                call_result=call_result,
                put_result=put_result,
                attempted_at=requested_at,
                completed_at=requested_at,
            )

            self._scheduler.transition(
                target_state=(
                    TradingDayState.PREPARING_LEVELS
                ),
                transitioned_at=requested_at,
            )

            self._completed_result = completed

            return completed

    def _validate_selected_pair(
        self,
        *,
        call_option: SelectedOption,
        put_option: SelectedOption,
        requested_expiry: date | None,
    ) -> None:
        if (
            call_option.option_type
            is not OptionType.CALL
        ):
            raise TradingDayOptionSelectionError(
                "CALL selection returned a non-CALL contract"
            )

        if (
            put_option.option_type
            is not OptionType.PUT
        ):
            raise TradingDayOptionSelectionError(
                "PUT selection returned a non-PUT contract"
            )

        if (
            call_option.contract.underlying_symbol
            != put_option.contract.underlying_symbol
        ):
            raise TradingDayOptionSelectionError(
                "selected CALL and PUT underlying symbols "
                "do not match"
            )

        if call_option.expiry != put_option.expiry:
            raise TradingDayOptionSelectionError(
                "selected CALL and PUT expiries do not match"
            )

        if (
            requested_expiry is not None
            and (
                call_option.expiry
                != requested_expiry
                or put_option.expiry
                != requested_expiry
            )
        ):
            raise TradingDayOptionSelectionError(
                "selected option expiry does not match "
                "requested_expiry"
            )

        if (
            call_option.security_id
            == put_option.security_id
        ):
            raise TradingDayOptionSelectionError(
                "selected CALL and PUT must have distinct "
                "security IDs"
            )

    def _validate_repeat_request(
        self,
        *,
        requested_expiry: date | None,
    ) -> None:
        if requested_expiry is None:
            return

        assert self._completed_result is not None
        assert (
            self._completed_result.selected_call
            is not None
        )

        if (
            self._completed_result
            .selected_call
            .expiry
            != requested_expiry
        ):
            raise TradingDayOptionSelectionError(
                "morning option pair is already fixed for "
                "another expiry"
            )

    def _validate_trading_date(
        self,
        requested_at: datetime,
    ) -> None:
        if (
            requested_at.date()
            != self._scheduler.trading_date
        ):
            raise TradingDayOptionSelectionError(
                "option-selection timestamp does not match "
                "scheduler trading_date"
            )

    @staticmethod
    def _validate_reference_price(
        reference_price: float,
    ) -> None:
        if (
            isinstance(reference_price, bool)
            or not isinstance(
                reference_price,
                (int, float),
            )
            or not isfinite(reference_price)
            or reference_price <= 0
        ):
            raise TradingDayOptionSelectionError(
                "reference_price must be a finite number "
                "greater than zero"
            )

    @staticmethod
    def _validate_datetime(
        value: datetime,
    ) -> None:
        if type(value) is not datetime:
            raise TypeError(
                "option-selection timestamp must be a datetime"
            )


class StartupRecoveryPort(Protocol):
    """
    Narrow M10 boundary to the existing M08 startup-recovery
    service.
    """

    def build_plan(
        self,
        *,
        trading_date: date,
    ) -> StartupRecoveryPlan:
        ...

    def recover(
        self,
        *,
        orchestrator: TradingRuntimeOrchestrator,
        source_runtime_id: str,
        checked_at: datetime,
    ) -> StartupRecoveryResult:
        ...


class TradingDayStartupError(RuntimeError):
    """
    Raised when M10 startup composition is internally
    inconsistent and cannot safely proceed.
    """


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayStartupResult:
    """
    Immutable result of M10 trading-day startup coordination.
    """

    trading_day: TradingDaySnapshot
    runtime: RuntimeSnapshot
    recovery_plan: StartupRecoveryPlan
    recovery_result: StartupRecoveryResult | None = None

    @property
    def is_ready(self) -> bool:
        return (
            not self.trading_day.is_terminal
            and self.runtime.state
            is RuntimeState.RUNNING
        )


class TradingDayStartupCoordinator:
    """
    Coordinates M10 trading-day startup with the existing
    M08 runtime and recovery lifecycle.

    Ownership remains separated:

        M10:
            trading-day eligibility and scheduler state

        M08:
            runtime startup, recovery, reconciliation and
            runtime execution gates

    This coordinator does not construct repositories, broker
    clients, event buses, or runtime components.
    """

    def __init__(
        self,
        *,
        scheduler: TradingDayScheduler,
        recovery_service: StartupRecoveryPort,
    ) -> None:
        self._scheduler = scheduler
        self._recovery_service = recovery_service

    @property
    def scheduler(self) -> TradingDayScheduler:
        return self._scheduler

    def build_recovery_plan(
        self,
    ) -> StartupRecoveryPlan:
        """
        Discover recovery requirements for this trading date.

        The plan is built before the application composition
        boundary constructs its TradingRuntimeOrchestrator so
        recovery_required can be supplied correctly.
        """

        return self._recovery_service.build_plan(
            trading_date=self._scheduler.trading_date
        )

    def start(
        self,
        *,
        orchestrator: TradingRuntimeOrchestrator,
        recovery_plan: StartupRecoveryPlan,
        started_at: datetime,
        recovery_checked_at: datetime | None = None,
        running_at: datetime | None = None,
    ) -> TradingDayStartupResult:
        """
        Start one trading day without bypassing M08 recovery.

        Trading day:
            calendar gate
              ->
            M08 runtime start
              ->
            M08 recovery when required
              ->
            M08 RUNNING

        Non-trading day:
            scheduler becomes NON_TRADING_DAY and the supplied
            runtime remains CREATED.
        """

        self._validate_datetime(
            started_at,
            name="started_at",
        )

        checked_at = (
            recovery_checked_at
            if recovery_checked_at is not None
            else started_at
        )

        run_at = (
            running_at
            if running_at is not None
            else checked_at
        )

        self._validate_datetime(
            checked_at,
            name="recovery_checked_at",
        )

        self._validate_datetime(
            run_at,
            name="running_at",
        )

        if checked_at < started_at:
            raise TradingDayStartupError(
                "recovery_checked_at cannot be before "
                "started_at"
            )

        if run_at < checked_at:
            raise TradingDayStartupError(
                "running_at cannot be before "
                "recovery_checked_at"
            )

        self._validate_runtime_contract(
            orchestrator=orchestrator,
            recovery_plan=recovery_plan,
        )

        trading_day = self._scheduler.start(
            started_at=started_at
        )

        if (
            trading_day.state
            is TradingDayState.NON_TRADING_DAY
        ):
            return TradingDayStartupResult(
                trading_day=trading_day,
                runtime=orchestrator.snapshot,
                recovery_plan=recovery_plan,
            )

        runtime = orchestrator.start(
            started_at=started_at
        )

        if runtime.state is RuntimeState.FAILED:
            trading_day = self._scheduler.fail(
                message="runtime startup failed",
                failed_at=started_at,
            )

            return TradingDayStartupResult(
                trading_day=trading_day,
                runtime=runtime,
                recovery_plan=recovery_plan,
            )

        recovery_result: (
            StartupRecoveryResult | None
        ) = None

        if recovery_plan.recovery_required:
            if (
                orchestrator.state
                is not RuntimeState.RECOVERING
            ):
                trading_day = self._scheduler.fail(
                    message=(
                        "runtime did not enter RECOVERING "
                        "state"
                    ),
                    failed_at=checked_at,
                )

                return TradingDayStartupResult(
                    trading_day=trading_day,
                    runtime=orchestrator.snapshot,
                    recovery_plan=recovery_plan,
                )

            source_runtime_id = (
                recovery_plan.source_runtime_id
            )

            if source_runtime_id is None:
                raise TradingDayStartupError(
                    "recovery-required plan must provide "
                    "source_runtime_id"
                )

            recovery_result = (
                self._recovery_service.recover(
                    orchestrator=orchestrator,
                    source_runtime_id=(
                        source_runtime_id
                    ),
                    checked_at=checked_at,
                )
            )

            if not recovery_result.completed:
                trading_day = self._scheduler.fail(
                    message=(
                        "startup recovery did not complete"
                    ),
                    failed_at=checked_at,
                )

                return TradingDayStartupResult(
                    trading_day=trading_day,
                    runtime=orchestrator.snapshot,
                    recovery_plan=recovery_plan,
                    recovery_result=recovery_result,
                )

        if orchestrator.state is not RuntimeState.READY:
            trading_day = self._scheduler.fail(
                message=(
                    "runtime did not reach READY state"
                ),
                failed_at=checked_at,
            )

            return TradingDayStartupResult(
                trading_day=trading_day,
                runtime=orchestrator.snapshot,
                recovery_plan=recovery_plan,
                recovery_result=recovery_result,
            )

        runtime = orchestrator.run(
            running_at=run_at
        )

        return TradingDayStartupResult(
            trading_day=self._scheduler.snapshot,
            runtime=runtime,
            recovery_plan=recovery_plan,
            recovery_result=recovery_result,
        )

    def _validate_runtime_contract(
        self,
        *,
        orchestrator: TradingRuntimeOrchestrator,
        recovery_plan: StartupRecoveryPlan,
    ) -> None:
        runtime_snapshot = orchestrator.snapshot

        if (
            runtime_snapshot.trading_date
            != self._scheduler.trading_date
        ):
            raise TradingDayStartupError(
                "runtime trading_date does not match "
                "scheduler trading_date"
            )

        if (
            runtime_snapshot.recovery_required
            != recovery_plan.recovery_required
        ):
            raise TradingDayStartupError(
                "runtime recovery_required does not match "
                "recovery plan"
            )

        if (
            recovery_plan.recovery_required
            and not (
                recovery_plan.source_runtime_id
                and
                recovery_plan.source_runtime_id.strip()
            )
        ):
            raise TradingDayStartupError(
                "recovery-required plan must provide "
                "source_runtime_id"
            )

    @staticmethod
    def _validate_datetime(
        value: datetime,
        *,
        name: str,
    ) -> None:
        if type(value) is not datetime:
            raise TypeError(
                f"{name} must be a datetime"
            )


__all__ = [
    "MorningOptionSelectionPort",
    "ReferenceWindowSchedule",
    "StartupRecoveryPort",
    "TradingCalendar",
    "TradingDayOptionSelectionCoordinator",
    "TradingDayOptionSelectionError",
    "TradingDayOptionSelectionResult",
    "TradingDayReferenceCoordinator",
    "TradingDayScheduler",
    "TradingDaySnapshot",
    "TradingDayStartupCoordinator",
    "TradingDayStartupError",
    "TradingDayStartupResult",
    "TradingDayState",
    "TradingDayTransitionError",
]
