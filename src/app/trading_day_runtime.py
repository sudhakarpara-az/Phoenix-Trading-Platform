"""
Phoenix M10 trading-day application runtime integration.

This module is an application-level composition boundary.

T14 Step 7 integrates:

    selected-option LevelEvent
        ->
    M10 + M08 entry gate
        ->
    fixed CE/PE direction resolution
        ->
    existing M04 SignalEngine

Important:

    - CALL/PUT is derived from the fixed morning-selected contract.
    - M05 is NOT invoked again after a level event.
    - M10/M08 entry permission is checked before M04 acquires a
      contract+level signal lock.
    - Existing M04 eligibility, duplicate, lock and re-entry
      policies remain authoritative.
    - No broker execution or position creation belongs here yet.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from threading import RLock
from typing import Any

from src.account.dhan_account_adapter import (
    DhanAccountAdapter,
)
from src.account.account_execution_gate import (
    AccountEntryBlockedError,
    AccountExecutionSafetyGate,
    AccountGatedEntryResult,
)
from src.database.entry_durability import (
    DurableEntryBrokerExecutionProvider,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyOrderRepository,
)
from src.execution.broker_execution_provider import (
    BrokerOrderSnapshot,
)
from src.execution.entry_order_sizing_policy import (
    EntryOrderSizing,
)
from src.execution.execution_service import (
    EntrySubmissionUncertainError,
    ExecutionServiceResult,
)
from src.execution.execution_types import (
    BrokerOrderStatus,
    ExecutionMode,
    ExecutionResult,
    OrderIntent,
)
from src.execution.filled_position_builder import (
    FilledPositionBuilder,
)
from src.execution.idempotency_guard import (
    IdempotencyKey,
    IdempotencyState,
)
from src.execution.m06_entry_runtime_adapter import (
    M06EntryRuntimeAdapter,
)
from src.execution.position_exit_types import (
    FilledPosition,
)
from src.risk.daily_risk_manager import (
    DailyRiskManager,
    DailyRiskSnapshot,
)
from src.risk.exposure_risk_policy import (
    ExposureRiskDecision,
    ExposureRiskPolicy,
)
from src.risk.filled_position_risk_initializer import (
    FilledPositionRiskInitializer,
)
from src.risk.option_target_mapper import (
    OptionTargetMapper,
)
from src.risk.position_pnl_tracker import (
    PositionPnLTracker,
)
from src.risk.risk_types import (
    ManagedPosition,
)

from src.market.market_types import MarketTick
from src.market.tick_processor import TickProcessor
from src.option_selection.option_types import (
    OptionType,
    SelectedOption,
)
from src.services.scheduler import (
    TradingDayCloseReadiness,
    TradingDayEntryGateCoordinator,
    TradingDayEntryGateDecision,
    TradingDayLevelPreparationResult,
    TradingDayTickMonitoringCoordinator,
)
from src.signals.eligibility_policy import (
    EligibilityContext,
)
from src.signals.signal_engine import (
    SignalEngine,
    SignalEngineResult,
)
from src.signals.signal_types import (
    SignalDirection,
    TradingSignal,
)
from src.strategy.strategy_types import (
    LevelEvent,
    LevelEventType,
    StrategySessionState,
)


class TradingDaySignalRuntimeReason(
    str,
    Enum,
):
    """
    Outcome of routing one T09 LevelEvent toward M04.
    """

    CREATED = "CREATED"

    UNSELECTED_CONTRACT = (
        "UNSELECTED_CONTRACT"
    )

    ENTRY_GATE_BLOCKED = (
        "ENTRY_GATE_BLOCKED"
    )

    SIGNAL_REJECTED = (
        "SIGNAL_REJECTED"
    )


class TradingDaySignalRuntimeError(
    RuntimeError
):
    """
    Fixed selected-contract ownership could not be proven.
    """


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDaySignalRuntimeResult:
    """
    Result of processing one selected-option LevelEvent.
    """

    event: LevelEvent

    reason: TradingDaySignalRuntimeReason

    selected_option: SelectedOption | None

    direction: SignalDirection | None

    entry_gate_decision: (
        TradingDayEntryGateDecision | None
    )

    signal_result: SignalEngineResult | None

    @property
    def signal(
        self,
    ) -> TradingSignal | None:
        if self.signal_result is None:
            return None

        return self.signal_result.signal

    @property
    def created(
        self,
    ) -> bool:
        return (
            self.reason
            is TradingDaySignalRuntimeReason.CREATED
        )


class TradingDaySignalRuntimeCoordinator:
    """
    Routes one T09 LevelEvent into the existing M04 SignalEngine.

    The two supplied SelectedOption instances are the fixed
    morning contracts chosen by M10.

    They are never replaced or re-selected in this coordinator.
    """

    def __init__(
        self,
        *,
        entry_gate:
            TradingDayEntryGateCoordinator,
        signal_engine: SignalEngine,
        selected_call: SelectedOption,
        selected_put: SelectedOption,
    ) -> None:
        self._entry_gate = entry_gate
        self._signal_engine = signal_engine

        self._selected_call = selected_call
        self._selected_put = selected_put

        self._validate_selected_pair()

    @property
    def entry_gate(
        self,
    ) -> TradingDayEntryGateCoordinator:
        return self._entry_gate

    @property
    def signal_engine(
        self,
    ) -> SignalEngine:
        """
        Return the exact M04 SignalEngine owned by this
        application runtime boundary.

        T14 entry lifecycle composition must use this same
        instance when marking a proven trade OPEN or releasing
        an accepted signal that never became a trade.
        """

        return self._signal_engine

    @property
    def selected_call(
        self,
    ) -> SelectedOption:
        return self._selected_call

    @property
    def selected_put(
        self,
    ) -> SelectedOption:
        return self._selected_put

    def process_event(
        self,
        event: LevelEvent,
    ) -> TradingDaySignalRuntimeResult:
        """
        Process one LevelEvent.

        Routine events for non-selected contracts are ignored
        without touching the runtime gate or M04 state.
        """

        if not isinstance(
            event,
            LevelEvent,
        ):
            raise TypeError(
                "event must be a LevelEvent"
            )

        resolved = (
            self._resolve_selected_contract(
                event
            )
        )

        if resolved is None:
            return TradingDaySignalRuntimeResult(
                event=event,
                reason=(
                    TradingDaySignalRuntimeReason
                    .UNSELECTED_CONTRACT
                ),
                selected_option=None,
                direction=None,
                entry_gate_decision=None,
                signal_result=None,
            )

        selected_option, direction = (
            resolved
        )

        # ----------------------------------------------------
        # Global entry permission BEFORE M04.
        #
        # SignalEngine.process() acquires a contract+level lock
        # when it creates a signal. Therefore scheduler/runtime
        # denial must occur before invoking M04.
        # ----------------------------------------------------

        gate_decision = (
            self._entry_gate.evaluate(
                evaluated_at=event.timestamp
            )
        )

        if not gate_decision.allowed:
            return TradingDaySignalRuntimeResult(
                event=event,
                reason=(
                    TradingDaySignalRuntimeReason
                    .ENTRY_GATE_BLOCKED
                ),
                selected_option=selected_option,
                direction=direction,
                entry_gate_decision=(
                    gate_decision
                ),
                signal_result=None,
            )

        # ----------------------------------------------------
        # Translate successful M10/M08 orchestration permission
        # into M04's existing eligibility context.
        #
        # M04 still independently enforces:
        #   - event trading date
        #   - 09:21 start
        #   - 15:15 end
        #   - K5/K6/K7 only
        #   - duplicate suppression
        #   - level lock
        #   - re-entry state
        # ----------------------------------------------------

        context = EligibilityContext(
            trading_date=(
                self._entry_gate
                .scheduler
                .trading_date
            ),
            session_state=(
                StrategySessionState.MONITORING
            ),
            trading_enabled=True,
            platform_halted=False,
        )

        signal_result = (
            self._signal_engine.process(
                event=event,
                direction=direction,
                context=context,
            )
        )

        if not signal_result.accepted:
            return TradingDaySignalRuntimeResult(
                event=event,
                reason=(
                    TradingDaySignalRuntimeReason
                    .SIGNAL_REJECTED
                ),
                selected_option=selected_option,
                direction=direction,
                entry_gate_decision=(
                    gate_decision
                ),
                signal_result=signal_result,
            )

        signal = signal_result.signal

        assert signal is not None

        # ----------------------------------------------------
        # Contract compatibility must survive M04 unchanged.
        # ----------------------------------------------------

        if (
            signal.instrument_security_id
            != selected_option.security_id
        ):
            raise TradingDaySignalRuntimeError(
                "M04 signal security ID does not match "
                "fixed selected option"
            )

        if (
            signal.instrument_symbol
            != selected_option.symbol
        ):
            raise TradingDaySignalRuntimeError(
                "M04 signal symbol does not match "
                "fixed selected option"
            )

        if signal.direction is not direction:
            raise TradingDaySignalRuntimeError(
                "M04 signal direction does not match "
                "fixed selected option"
            )

        return TradingDaySignalRuntimeResult(
            event=event,
            reason=(
                TradingDaySignalRuntimeReason.CREATED
            ),
            selected_option=selected_option,
            direction=direction,
            entry_gate_decision=gate_decision,
            signal_result=signal_result,
        )

    def _resolve_selected_contract(
        self,
        event: LevelEvent,
    ) -> tuple[
        SelectedOption,
        SignalDirection,
    ] | None:
        if (
            event.instrument_security_id
            == self._selected_call.security_id
        ):
            if (
                event.instrument_symbol
                != self._selected_call.symbol
            ):
                raise TradingDaySignalRuntimeError(
                    "CALL event symbol does not match "
                    "fixed selected CALL"
                )

            return (
                self._selected_call,
                SignalDirection.CALL,
            )

        if (
            event.instrument_security_id
            == self._selected_put.security_id
        ):
            if (
                event.instrument_symbol
                != self._selected_put.symbol
            ):
                raise TradingDaySignalRuntimeError(
                    "PUT event symbol does not match "
                    "fixed selected PUT"
                )

            return (
                self._selected_put,
                SignalDirection.PUT,
            )

        return None

    def _validate_selected_pair(
        self,
    ) -> None:
        if (
            self._selected_call.option_type
            is not OptionType.CALL
        ):
            raise ValueError(
                "selected_call must be CALL"
            )

        if (
            self._selected_put.option_type
            is not OptionType.PUT
        ):
            raise ValueError(
                "selected_put must be PUT"
            )

        if (
            self._selected_call.security_id
            == self._selected_put.security_id
        ):
            raise ValueError(
                "selected CALL and PUT must have "
                "different security IDs"
            )

        if (
            self._selected_call.expiry
            != self._selected_put.expiry
        ):
            raise ValueError(
                "selected CALL and PUT must have "
                "the same expiry"
            )

        if (
            self._selected_call
            .contract
            .underlying_symbol
            != self._selected_put
            .contract
            .underlying_symbol
        ):
            raise ValueError(
                "selected CALL and PUT must have "
                "the same underlying"
            )


__all__ = [
    "TradingDaySignalRuntimeCoordinator",
    "TradingDaySignalRuntimeError",
    "TradingDaySignalRuntimeReason",
    "TradingDaySignalRuntimeResult",
]



# ============================================================
# T14 accepted-signal entry lifecycle
# ============================================================


class TradingDayEntryRuntimeReason(
    str,
    Enum,
):
    """
    Application-level outcome for one accepted-signal entry.
    """

    SIGNAL_NOT_CREATED = (
        "SIGNAL_NOT_CREATED"
    )

    DAILY_RISK_BLOCKED = (
        "DAILY_RISK_BLOCKED"
    )

    EXPOSURE_RISK_BLOCKED = (
        "EXPOSURE_RISK_BLOCKED"
    )

    ACCOUNT_BLOCKED = (
        "ACCOUNT_BLOCKED"
    )

    EXECUTION_REJECTED = (
        "EXECUTION_REJECTED"
    )

    DRY_RUN_COMPLETED = (
        "DRY_RUN_COMPLETED"
    )

    ENTRY_PENDING = (
        "ENTRY_PENDING"
    )

    ENTRY_FILLED = (
        "ENTRY_FILLED"
    )

    ENTRY_CANCELLED = (
        "ENTRY_CANCELLED"
    )

    RECONCILIATION_REQUIRED = (
        "RECONCILIATION_REQUIRED"
    )

    OPERATIONAL_FAILURE = (
        "OPERATIONAL_FAILURE"
    )


class TradingDayEntryRuntimeError(
    RuntimeError
):
    """
    T14 entry composition invariant could not be proven.
    """


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayEntryReconciliationContext:
    """
    Exact state retained after Phoenix crosses the LIVE broker
    boundary but the entry is not yet safely resolved.

    No new BUY may be created from this signal while this context
    exists.
    """

    signal: TradingSignal

    selected_option: SelectedOption

    levels: Any

    intent: OrderIntent

    execution_result: ExecutionResult | None

    started_at: datetime

    latest_snapshot: BrokerOrderSnapshot | None = None

    filled_position: FilledPosition | None = None


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayEntryRuntimeResult:
    """
    Complete T14 entry-lifecycle result.
    """

    signal_runtime_result: TradingDaySignalRuntimeResult

    reason: TradingDayEntryRuntimeReason

    sizing: EntryOrderSizing | None = None

    daily_risk: DailyRiskSnapshot | None = None

    exposure_risk: ExposureRiskDecision | None = None

    account_result: AccountGatedEntryResult | None = None

    execution_result: ExecutionServiceResult | None = None

    broker_snapshot: BrokerOrderSnapshot | None = None

    filled_position: FilledPosition | None = None

    managed_position: ManagedPosition | None = None

    message: str | None = None

    @property
    def signal(
        self,
    ) -> TradingSignal | None:
        return self.signal_runtime_result.signal

    @property
    def position_opened(
        self,
    ) -> bool:
        return (
            self.reason
            is TradingDayEntryRuntimeReason
            .ENTRY_FILLED
            and self.managed_position
            is not None
        )

    @property
    def requires_reconciliation(
        self,
    ) -> bool:
        return (
            self.reason
            is TradingDayEntryRuntimeReason
            .RECONCILIATION_REQUIRED
        )


class TradingDayEntryRuntimeCoordinator:
    """
    T14 application boundary from an accepted M04 signal through
    M07/M09/M06 and finally into an M07 ManagedPosition.

    Ownership rules:

        TradingDaySignalRuntimeCoordinator
            owns the exact M04 SignalEngine.

        AccountExecutionSafetyGate
            delegates to the exact supplied M06EntryRuntimeAdapter.

        ExposureRiskPolicy,
        DailyRiskManager,
        FilledPositionRiskInitializer
            all use the exact same PositionRegistry.

        TradingDayLevelPreparationResult
            owns the exact fixed CALL/PUT contracts and separate
            same-contract KSLevels for the day.

    The coordinator never submits a second BUY while a previous
    broker outcome for the same signal remains unresolved.
    """

    def __init__(
        self,
        *,
        signal_runtime:
            TradingDaySignalRuntimeCoordinator,
        entry_adapter:
            M06EntryRuntimeAdapter,
        account_gate:
            AccountExecutionSafetyGate,
        exposure_policy:
            ExposureRiskPolicy,
        daily_risk_manager:
            DailyRiskManager,
        pnl_tracker:
            PositionPnLTracker,
        filled_position_builder:
            FilledPositionBuilder,
        position_initializer:
            FilledPositionRiskInitializer,
        target_mapper:
            OptionTargetMapper,
        level_preparation:
            TradingDayLevelPreparationResult,
    ) -> None:
        self._signal_runtime = (
            signal_runtime
        )

        self._entry_adapter = (
            entry_adapter
        )

        self._account_gate = (
            account_gate
        )

        self._exposure_policy = (
            exposure_policy
        )

        self._daily_risk_manager = (
            daily_risk_manager
        )

        self._pnl_tracker = (
            pnl_tracker
        )

        self._filled_position_builder = (
            filled_position_builder
        )

        self._position_initializer = (
            position_initializer
        )

        self._target_mapper = (
            target_mapper
        )

        self._level_preparation = (
            level_preparation
        )

        self._results: dict[
            str,
            TradingDayEntryRuntimeResult,
        ] = {}

        self._pending: dict[
            str,
            TradingDayEntryReconciliationContext,
        ] = {}

        self._lock = RLock()

        self._validate_composition()

    # --------------------------------------------------------
    # Public ownership accessors
    # --------------------------------------------------------

    @property
    def signal_runtime(
        self,
    ) -> TradingDaySignalRuntimeCoordinator:
        return self._signal_runtime


    @property
    def level_preparation(
        self,
    ) -> TradingDayLevelPreparationResult:
        """
        Return the exact immutable M10 level preparation.

        No KS recalculation, option selection, persistence,
        broker access, or runtime mutation occurs here.
        """

        return self._level_preparation

    @property
    def entry_adapter(
        self,
    ) -> M06EntryRuntimeAdapter:
        return self._entry_adapter

    @property
    def account_gate(
        self,
    ) -> AccountExecutionSafetyGate:
        return self._account_gate

    @property
    def position_registry(
        self,
    ):
        return (
            self._position_initializer.registry
        )

    @property
    def pending_count(
        self,
    ) -> int:
        with self._lock:
            return len(
                self._pending
            )

    def get_result(
        self,
        signal_id: str,
    ) -> TradingDayEntryRuntimeResult | None:
        normalized = self._normalize_signal_id(
            signal_id
        )

        with self._lock:
            return self._results.get(
                normalized
            )

    def get_pending_entry(
        self,
        signal_id: str,
    ) -> (
        TradingDayEntryReconciliationContext
        | None
    ):
        normalized = self._normalize_signal_id(
            signal_id
        )

        with self._lock:
            return self._pending.get(
                normalized
            )

    def cancel_pending_entry(
        self,
        signal_id: str,
        *,
        cancelled_at: datetime,
    ) -> TradingDayEntryRuntimeResult:
        """
        Request cancellation of one unresolved LIVE BUY.

        Cancellation never assumes the broker accepted the
        request. M06 immediately refreshes authoritative order
        status and the existing broker-snapshot resolver decides:

            CANCELLED + zero fill
                -> terminal cancellation

            FILLED
                -> build/manage position normally

            OPEN/PENDING
                -> remains pending

            PARTIAL/UNKNOWN/etc.
                -> reconciliation required
        """

        normalized = self._normalize_signal_id(
            signal_id
        )

        if type(cancelled_at) is not datetime:
            raise TypeError(
                "cancelled_at must be a datetime"
            )

        with self._lock:
            context = self._pending.get(
                normalized
            )

            if context is None:
                raise KeyError(
                    "pending entry not found: "
                    f"{normalized}"
                )

            if cancelled_at < context.started_at:
                raise ValueError(
                    "cancelled_at cannot be before "
                    "entry start time"
                )

            execution_result = (
                context.execution_result
            )

            if (
                execution_result is None
                or execution_result
                .broker_reference is None
            ):
                existing = (
                    self._results[
                        normalized
                    ]
                )

                unresolved = replace(
                    existing,
                    reason=(
                        TradingDayEntryRuntimeReason
                        .RECONCILIATION_REQUIRED
                    ),
                    message=(
                        existing.message
                        or "pending entry has no broker "
                        "reference for cancellation"
                    ),
                )

                self._results[
                    normalized
                ] = unresolved

                return unresolved

            try:
                snapshot = (
                    self._entry_adapter
                    .execution_service
                    .cancel_entry_order(
                        intent=context.intent,
                        execution_result=(
                            execution_result
                        ),
                    )
                )

            except Exception as exc:
                existing = (
                    self._results[
                        normalized
                    ]
                )

                unresolved = replace(
                    existing,
                    reason=(
                        TradingDayEntryRuntimeReason
                        .RECONCILIATION_REQUIRED
                    ),
                    message=str(exc),
                )

                self._results[
                    normalized
                ] = unresolved

                return unresolved

            context = replace(
                context,
                latest_snapshot=snapshot,
            )

            self._pending[
                normalized
            ] = context

            return self._resolve_broker_snapshot(
                signal_key=normalized,
                snapshot=snapshot,
                resolved_at=cancelled_at,
            )

    def cancel_pending_entries(
        self,
        *,
        cancelled_at: datetime,
    ) -> tuple[
        TradingDayEntryRuntimeResult,
        ...,
    ]:
        """
        Attempt cancellation of every locally unresolved BUY.

        The pending-key snapshot is deterministic. A concurrent
        reconciliation that already removed one entry is treated
        as already resolved rather than as a batch failure.
        """

        if type(cancelled_at) is not datetime:
            raise TypeError(
                "cancelled_at must be a datetime"
            )

        with self._lock:
            signal_ids = tuple(
                sorted(
                    self._pending
                )
            )

        results: list[
            TradingDayEntryRuntimeResult
        ] = []

        for signal_id in signal_ids:
            try:
                result = self.cancel_pending_entry(
                    signal_id,
                    cancelled_at=cancelled_at,
                )

            except KeyError:
                # Another reconciliation resolved the entry
                # after the deterministic key snapshot.
                continue

            results.append(
                result
            )

        return tuple(
            results
        )


    # --------------------------------------------------------
    # Initial accepted-signal processing
    # --------------------------------------------------------

    def process_signal_result(
        self,
        signal_runtime_result:
            TradingDaySignalRuntimeResult,
        *,
        dry_run: bool,
        requested_at: datetime,
    ) -> TradingDayEntryRuntimeResult:
        """
        Process one T14/M04 signal result exactly once.

        A later call for the same SignalId returns the already
        recorded result and never resubmits the broker order.
        """

        if not isinstance(
            signal_runtime_result,
            TradingDaySignalRuntimeResult,
        ):
            raise TypeError(
                "signal_runtime_result must be "
                "TradingDaySignalRuntimeResult"
            )

        if type(dry_run) is not bool:
            raise TypeError(
                "dry_run must be bool"
            )

        if type(requested_at) is not datetime:
            raise TypeError(
                "requested_at must be a datetime"
            )

        if not signal_runtime_result.created:
            return TradingDayEntryRuntimeResult(
                signal_runtime_result=(
                    signal_runtime_result
                ),
                reason=(
                    TradingDayEntryRuntimeReason
                    .SIGNAL_NOT_CREATED
                ),
            )

        signal = (
            signal_runtime_result.signal
        )

        selected_option = (
            signal_runtime_result
            .selected_option
        )

        if (
            signal is None
            or selected_option is None
        ):
            raise TradingDayEntryRuntimeError(
                "created signal runtime result must "
                "contain signal and selected option"
            )

        if (
            requested_at.date()
            != signal.trading_date
        ):
            raise ValueError(
                "requested_at date does not match "
                "signal trading date"
            )

        if (
            requested_at
            < signal.generated_at
        ):
            raise ValueError(
                "requested_at cannot be before "
                "signal generation"
            )

        self._validate_signal_identity(
            signal=signal,
            selected_option=selected_option,
        )

        signal_key = (
            signal.signal_id.value
        )

        with self._lock:
            existing = (
                self._results.get(
                    signal_key
                )
            )

            if existing is not None:
                return existing

            levels = self._resolve_levels(
                signal=signal,
                selected_option=(
                    selected_option
                ),
            )

            # ------------------------------------------------
            # Shared M06 sizing
            # ------------------------------------------------

            sizing = (
                self._entry_adapter
                .calculate_sizing(
                    selected_option=(
                        selected_option
                    )
                )
            )

            # ------------------------------------------------
            # M07 daily risk
            # ------------------------------------------------

            daily_risk = (
                self._daily_risk_manager
                .build_snapshot(
                    trading_date=(
                        signal.trading_date
                    ),
                    position_pnls=(
                        self._pnl_tracker
                        .pnl_map()
                    ),
                    captured_at=(
                        requested_at
                    ),
                )
            )

            if not daily_risk.new_entries_allowed:
                return self._abort_and_store(
                    signal_runtime_result=(
                        signal_runtime_result
                    ),
                    reason=(
                        TradingDayEntryRuntimeReason
                        .DAILY_RISK_BLOCKED
                    ),
                    sizing=sizing,
                    daily_risk=daily_risk,
                    message=(
                        daily_risk.message
                        or daily_risk
                        .lock_reason.value
                    ),
                )

            # ------------------------------------------------
            # M07 proposed exposure
            #
            # Use the configured maximum stop risk as the
            # conservative pre-entry risk amount. The actual
            # post-fill stop may be slightly tighter after tick
            # normalization, never wider.
            # ------------------------------------------------

            stop_risk_points = (
                self._position_initializer
                .stop_loss_policy
                .config
                .risk_points
            )

            exposure_risk = (
                self._exposure_policy
                .evaluate_new_position(
                    quantity=(
                        sizing
                        .requested_quantity
                    ),
                    stop_risk_points=(
                        stop_risk_points
                    ),
                )
            )

            if not exposure_risk.eligible:
                return self._abort_and_store(
                    signal_runtime_result=(
                        signal_runtime_result
                    ),
                    reason=(
                        TradingDayEntryRuntimeReason
                        .EXPOSURE_RISK_BLOCKED
                    ),
                    sizing=sizing,
                    daily_risk=daily_risk,
                    exposure_risk=(
                        exposure_risk
                    ),
                    message=(
                        exposure_risk.message
                        or exposure_risk
                        .reason.value
                    ),
                )

            # ------------------------------------------------
            # M09 account gate -> M06
            # ------------------------------------------------

            try:
                account_result = (
                    self._account_gate
                    .execute_entry(
                        signal=signal,
                        selected_option=(
                            selected_option
                        ),
                        required_cash=(
                            sizing.required_cash
                        ),
                        dry_run=dry_run,
                        requested_at=(
                            requested_at
                        ),
                    )
                )

            except EntrySubmissionUncertainError as exc:
                self._validate_intent_identity(
                    intent=exc.intent,
                    signal=signal,
                    selected_option=(
                        selected_option
                    ),
                )

                context = (
                    TradingDayEntryReconciliationContext(
                        signal=signal,
                        selected_option=(
                            selected_option
                        ),
                        levels=levels,
                        intent=exc.intent,
                        execution_result=None,
                        started_at=requested_at,
                    )
                )

                self._pending[
                    signal_key
                ] = context

                result = (
                    TradingDayEntryRuntimeResult(
                        signal_runtime_result=(
                            signal_runtime_result
                        ),
                        reason=(
                            TradingDayEntryRuntimeReason
                            .RECONCILIATION_REQUIRED
                        ),
                        sizing=sizing,
                        daily_risk=daily_risk,
                        exposure_risk=(
                            exposure_risk
                        ),
                        message=str(exc),
                    )
                )

                self._results[
                    signal_key
                ] = result

                return result

            except AccountEntryBlockedError as exc:
                return self._abort_and_store(
                    signal_runtime_result=(
                        signal_runtime_result
                    ),
                    reason=(
                        TradingDayEntryRuntimeReason
                        .ACCOUNT_BLOCKED
                    ),
                    sizing=sizing,
                    daily_risk=daily_risk,
                    exposure_risk=(
                        exposure_risk
                    ),
                    message=str(exc),
                )

            except Exception as exc:
                if self._broker_boundary_crossed(
                    signal
                ):
                    result = (
                        TradingDayEntryRuntimeResult(
                            signal_runtime_result=(
                                signal_runtime_result
                            ),
                            reason=(
                                TradingDayEntryRuntimeReason
                                .RECONCILIATION_REQUIRED
                            ),
                            sizing=sizing,
                            daily_risk=daily_risk,
                            exposure_risk=(
                                exposure_risk
                            ),
                            message=str(exc),
                        )
                    )

                    self._results[
                        signal_key
                    ] = result

                    return result

                return self._abort_and_store(
                    signal_runtime_result=(
                        signal_runtime_result
                    ),
                    reason=(
                        TradingDayEntryRuntimeReason
                        .OPERATIONAL_FAILURE
                    ),
                    sizing=sizing,
                    daily_risk=daily_risk,
                    exposure_risk=(
                        exposure_risk
                    ),
                    message=str(exc),
                )

            execution = (
                account_result.execution
            )

            if execution is None:
                return self._abort_and_store(
                    signal_runtime_result=(
                        signal_runtime_result
                    ),
                    reason=(
                        TradingDayEntryRuntimeReason
                        .EXECUTION_REJECTED
                    ),
                    sizing=sizing,
                    daily_risk=daily_risk,
                    exposure_risk=(
                        exposure_risk
                    ),
                    account_result=(
                        account_result
                    ),
                    message=(
                        "M09 allowed entry but "
                        "M06 returned no execution"
                    ),
                )

            intent = execution.intent

            broker_execution = (
                execution.execution_result
            )

            # No broker submission occurred.
            if (
                intent is None
                or broker_execution is None
            ):
                message = None

                if hasattr(
                    execution,
                    "eligibility",
                ):
                    eligibility = (
                        execution.eligibility
                    )

                    message = (
                        getattr(
                            eligibility,
                            "message",
                            None,
                        )
                    )

                    if message is None:
                        reason = getattr(
                            eligibility,
                            "reason",
                            None,
                        )

                        message = getattr(
                            reason,
                            "value",
                            None,
                        )

                return self._abort_and_store(
                    signal_runtime_result=(
                        signal_runtime_result
                    ),
                    reason=(
                        TradingDayEntryRuntimeReason
                        .EXECUTION_REJECTED
                    ),
                    sizing=sizing,
                    daily_risk=daily_risk,
                    exposure_risk=(
                        exposure_risk
                    ),
                    account_result=(
                        account_result
                    ),
                    execution_result=(
                        execution
                    ),
                    message=(
                        message
                        or "M06 did not cross broker boundary"
                    ),
                )

            self._validate_intent_identity(
                intent=intent,
                signal=signal,
                selected_option=(
                    selected_option
                ),
            )

            # ------------------------------------------------
            # Dry run is a completed simulation only.
            # It must never create a real M07 position.
            # ------------------------------------------------

            if dry_run:
                if (
                    intent.execution_mode
                    is not ExecutionMode.DRY_RUN
                ):
                    raise TradingDayEntryRuntimeError(
                        "dry-run request produced "
                        "non-dry-run intent"
                    )

                return self._abort_and_store(
                    signal_runtime_result=(
                        signal_runtime_result
                    ),
                    reason=(
                        TradingDayEntryRuntimeReason
                        .DRY_RUN_COMPLETED
                    ),
                    sizing=sizing,
                    daily_risk=daily_risk,
                    exposure_risk=(
                        exposure_risk
                    ),
                    account_result=(
                        account_result
                    ),
                    execution_result=(
                        execution
                    ),
                )

            if (
                intent.execution_mode
                is not ExecutionMode.LIVE
            ):
                raise TradingDayEntryRuntimeError(
                    "LIVE entry request produced "
                    "non-LIVE intent"
                )

            context = (
                TradingDayEntryReconciliationContext(
                    signal=signal,
                    selected_option=(
                        selected_option
                    ),
                    levels=levels,
                    intent=intent,
                    execution_result=(
                        broker_execution
                    ),
                    started_at=requested_at,
                )
            )

            self._pending[
                signal_key
            ] = context

            # Record before any broker refresh so an exception
            # during reconciliation still leaves an explicit
            # application-level unresolved entry.
            pending_result = (
                TradingDayEntryRuntimeResult(
                    signal_runtime_result=(
                        signal_runtime_result
                    ),
                    reason=(
                        TradingDayEntryRuntimeReason
                        .ENTRY_PENDING
                    ),
                    sizing=sizing,
                    daily_risk=daily_risk,
                    exposure_risk=(
                        exposure_risk
                    ),
                    account_result=(
                        account_result
                    ),
                    execution_result=(
                        execution
                    ),
                )
            )

            self._results[
                signal_key
            ] = pending_result

            # A broker result without a reference cannot be
            # refreshed through the current M06 provider contract.
            if (
                broker_execution
                .broker_reference
                is None
            ):
                unresolved = replace(
                    pending_result,
                    reason=(
                        TradingDayEntryRuntimeReason
                        .RECONCILIATION_REQUIRED
                    ),
                    message=(
                        broker_execution.message
                        or "LIVE broker result has no "
                        "reconciliation reference"
                    ),
                )

                self._results[
                    signal_key
                ] = unresolved

                return unresolved

            return self._refresh_and_resolve(
                signal_key=signal_key,
                reconciled_at=(
                    requested_at
                ),
            )

    # --------------------------------------------------------
    # Existing submitted entry reconciliation
    # --------------------------------------------------------

    def reconcile_entry(
        self,
        signal_id: str,
        *,
        reconciled_at: datetime,
    ) -> TradingDayEntryRuntimeResult:
        """
        Reconcile one unresolved LIVE entry without submitting
        another BUY.
        """

        normalized = self._normalize_signal_id(
            signal_id
        )

        if type(reconciled_at) is not datetime:
            raise TypeError(
                "reconciled_at must be a datetime"
            )

        with self._lock:
            context = self._pending.get(
                normalized
            )

            if context is None:
                raise KeyError(
                    "pending entry not found: "
                    f"{normalized}"
                )

            if (
                reconciled_at
                < context.started_at
            ):
                raise ValueError(
                    "reconciled_at cannot be before "
                    "entry start time"
                )

            if (
                context.execution_result is None
                or context.execution_result
                .broker_reference
                is None
            ):
                existing = (
                    self._results[
                        normalized
                    ]
                )

                unresolved = replace(
                    existing,
                    reason=(
                        TradingDayEntryRuntimeReason
                        .RECONCILIATION_REQUIRED
                    ),
                    message=(
                        existing.message
                        or "entry has no broker reference "
                        "for automatic reconciliation"
                    ),
                )

                self._results[
                    normalized
                ] = unresolved

                return unresolved

            return self._refresh_and_resolve(
                signal_key=normalized,
                reconciled_at=(
                    reconciled_at
                ),
            )

    # --------------------------------------------------------
    # Broker truth handling
    # --------------------------------------------------------

    def _refresh_and_resolve(
        self,
        *,
        signal_key: str,
        reconciled_at: datetime,
    ) -> TradingDayEntryRuntimeResult:
        context = self._pending[
            signal_key
        ]

        assert (
            context.execution_result
            is not None
        )

        try:
            snapshot = (
                self._entry_adapter
                .execution_service
                .refresh_entry_order_status(
                    intent=context.intent,
                    execution_result=(
                        context.execution_result
                    ),
                )
            )

        except Exception as exc:
            existing = (
                self._results[
                    signal_key
                ]
            )

            unresolved = replace(
                existing,
                reason=(
                    TradingDayEntryRuntimeReason
                    .RECONCILIATION_REQUIRED
                ),
                message=str(exc),
            )

            self._results[
                signal_key
            ] = unresolved

            return unresolved

        context = replace(
            context,
            latest_snapshot=snapshot,
        )

        self._pending[
            signal_key
        ] = context

        return self._resolve_broker_snapshot(
            signal_key=signal_key,
            snapshot=snapshot,
            resolved_at=reconciled_at,
        )

    def _resolve_broker_snapshot(
        self,
        *,
        signal_key: str,
        snapshot: BrokerOrderSnapshot,
        resolved_at: datetime,
    ) -> TradingDayEntryRuntimeResult:
        context = self._pending[
            signal_key
        ]

        existing = (
            self._results[
                signal_key
            ]
        )

        status = snapshot.status

        if (
            status
            is BrokerOrderStatus.FILLED
        ):
            return self._finalize_filled_entry(
                signal_key=signal_key,
                snapshot=snapshot,
                resolved_at=resolved_at,
            )

        if (
            status
            is BrokerOrderStatus.CANCELLED
            and snapshot.filled_quantity == 0
        ):
            try:
                self._persist_cancelled_entry(
                    context=context,
                    snapshot=snapshot,
                )

            except Exception as exc:
                unresolved = replace(
                    existing,
                    reason=(
                        TradingDayEntryRuntimeReason
                        .RECONCILIATION_REQUIRED
                    ),
                    broker_snapshot=snapshot,
                    message=str(exc),
                )

                self._results[
                    signal_key
                ] = unresolved

                return unresolved

            self._release_signal_lock(
                context.signal
            )

            self._pending.pop(
                signal_key,
                None,
            )

            result = replace(
                existing,
                reason=(
                    TradingDayEntryRuntimeReason
                    .ENTRY_CANCELLED
                ),
                broker_snapshot=snapshot,
                message=snapshot.message,
            )

            self._results[
                signal_key
            ] = result

            return result

        if status in {
            BrokerOrderStatus.PENDING,
            BrokerOrderStatus.OPEN,
        }:
            result = replace(
                existing,
                reason=(
                    TradingDayEntryRuntimeReason
                    .ENTRY_PENDING
                ),
                broker_snapshot=snapshot,
                message=snapshot.message,
            )

            self._results[
                signal_key
            ] = result

            return result

        # PARTIALLY_FILLED:
        #     market exposure exists but a full M07 position
        #     cannot yet be constructed.
        #
        # UNKNOWN:
        #     broker truth is not proven.
        #
        # REJECTED:
        #     current M06 contract intentionally keeps the
        #     SUBMITTED idempotency record blocked.
        #
        # CANCELLED with non-zero fill:
        #     exposure exists and requires explicit recovery.
        result = replace(
            existing,
            reason=(
                TradingDayEntryRuntimeReason
                .RECONCILIATION_REQUIRED
            ),
            broker_snapshot=snapshot,
            message=(
                snapshot.message
                or (
                    "entry requires reconciliation: "
                    f"{status.value}"
                )
            ),
        )

        self._results[
            signal_key
        ] = result

        return result

    # --------------------------------------------------------
    # Proven full fill -> M07
    # --------------------------------------------------------

    def _finalize_filled_entry(
        self,
        *,
        signal_key: str,
        snapshot: BrokerOrderSnapshot,
        resolved_at: datetime,
    ) -> TradingDayEntryRuntimeResult:
        context = self._pending[
            signal_key
        ]

        existing_result = (
            self._results[
                signal_key
            ]
        )

        try:
            execution_result = (
                context.execution_result
            )

            if execution_result is None:
                raise TradingDayEntryRuntimeError(
                    "filled entry requires "
                    "execution result"
                )

            execution_service = (
                self._entry_adapter
                .execution_service
            )

            broker_provider = getattr(
                execution_service,
                "broker_provider",
                None,
            )

            durable_provider = (
                broker_provider
                if isinstance(
                    broker_provider,
                    DurableEntryBrokerExecutionProvider,
                )
                else None
            )

            # --------------------------------------------
            # Crash-safe boundary 1.
            #
            # M06 has already reconciled this order to
            # FILLED. Persist authoritative broker fill
            # facts BEFORE constructing M07 state.
            #
            # Non-durable M06 compositions intentionally
            # preserve their existing behavior.
            # --------------------------------------------

            if durable_provider is not None:
                lifecycle_snapshot = (
                    execution_service
                    .order_state_machine
                    .snapshot(
                        context.intent.intent_id
                    )
                )

                persistence = (
                    durable_provider.persistence
                )

                persistence.persist_broker_execution_result(
                    intent=context.intent,
                    result=execution_result,
                    broker_snapshot=snapshot,
                    lifecycle_snapshot=(
                        lifecycle_snapshot
                    ),
                )

            filled_position = (
                context.filled_position
            )

            if filled_position is None:
                filled_position = (
                    self._filled_position_builder
                    .build(
                        intent=context.intent,
                        broker_snapshot=snapshot,
                    )
                )

                context = replace(
                    context,
                    latest_snapshot=snapshot,
                    filled_position=(
                        filled_position
                    ),
                )

                self._pending[
                    signal_key
                ] = context

            finalized_at = max(
                resolved_at,
                snapshot.updated_at,
                filled_position.filled_at,
            )

            # --------------------------------------------
            # Map the same-contract target BEFORE the
            # initializer mutates PositionRegistry.
            # --------------------------------------------

            mapping_result = (
                self._target_mapper
                .map_target(
                    position=filled_position,
                    levels=context.levels,
                    mapped_at=finalized_at,
                )
            )

            if not mapping_result.mapped:
                raise TradingDayEntryRuntimeError(
                    "filled position target was not mapped"
                )

            target_definition = (
                mapping_result.mapping
                .target_definition
            )

            registry = (
                self._position_initializer
                .registry
            )

            managed = registry.get(
                filled_position.position_id
            )

            if managed is None:
                managed = (
                    self._position_initializer
                    .initialize(
                        position=(
                            filled_position
                        ),
                        initialized_at=(
                            finalized_at
                        ),
                    )
                )

            elif (
                managed.position
                != filled_position
            ):
                raise TradingDayEntryRuntimeError(
                    "existing managed position does not "
                    "match reconciled filled position"
                )

            # Attach target idempotently.
            if managed.target is None:
                managed = replace(
                    managed,
                    target=target_definition,
                    updated_at=max(
                        managed.updated_at,
                        finalized_at,
                    ),
                )

                managed = registry.replace(
                    managed
                )

            elif (
                managed.target
                != target_definition
            ):
                raise TradingDayEntryRuntimeError(
                    "existing managed target conflicts "
                    "with same-contract target mapping"
                )

            # --------------------------------------------
            # Crash-safe boundaries 2 and 3.
            #
            # The exact M07 ManagedPosition now contains:
            #
            #   broker average fill
            #   stop loss
            #   same-contract mapped target
            #
            # Persist PositionRecord first. Only after that
            # independent transaction is proven durable may the
            # durable OrderRecord become FILLED and link to it.
            # --------------------------------------------

            if durable_provider is not None:
                lifecycle_snapshot = (
                    execution_service
                    .order_state_machine
                    .snapshot(
                        context.intent.intent_id
                    )
                )

                persistence = (
                    durable_provider.persistence
                )

                persistence.persist_broker_execution_result(
                    intent=context.intent,
                    result=execution_result,
                    broker_snapshot=snapshot,
                    lifecycle_snapshot=(
                        lifecycle_snapshot
                    ),
                    managed_position=managed,
                    terminalize_order=True,
                )

            # --------------------------------------------
            # P&L comes only after durable order+position
            # completion.
            # --------------------------------------------

            # Register P&L exactly once.
            pnl_state = (
                self._pnl_tracker.get(
                    filled_position.position_id
                )
            )

            if pnl_state is None:
                self._pnl_tracker.register(
                    position=managed,
                    registered_at=(
                        finalized_at
                    ),
                )

            # M04 is deliberately LAST.
            #
            # At this point:
            #
            #   M06 broker FILLED is proven
            #   durable fill facts exist when durability is enabled
            #   M07 ManagedPosition + target exist
            #   durable PositionRecord exists when enabled
            #   durable OrderRecord is FILLED when enabled
            #   P&L registration exists
            #
            # Only now may the M04 trade lock become ACTIVE.
            self._signal_runtime.signal_engine.mark_trade_open(
                context.signal
            )

        except Exception as exc:
            unresolved = replace(
                existing_result,
                reason=(
                    TradingDayEntryRuntimeReason
                    .RECONCILIATION_REQUIRED
                ),
                broker_snapshot=snapshot,
                filled_position=(
                    context.filled_position
                ),
                message=str(exc),
            )

            self._results[
                signal_key
            ] = unresolved

            return unresolved

        self._pending.pop(
            signal_key,
            None,
        )

        result = replace(
            existing_result,
            reason=(
                TradingDayEntryRuntimeReason
                .ENTRY_FILLED
            ),
            broker_snapshot=snapshot,
            filled_position=(
                filled_position
            ),
            managed_position=managed,
            message=None,
        )

        self._results[
            signal_key
        ] = result

        return result

    # --------------------------------------------------------
    # Safe pre-broker abort
    # --------------------------------------------------------

    def _persist_cancelled_entry(
        self,
        *,
        context:
            TradingDayEntryReconciliationContext,
        snapshot: BrokerOrderSnapshot,
    ) -> None:
        """
        Checkpoint proven zero-fill cancellation when the active
        production M06 broker provider is the durable provider.

        Non-durable unit compositions deliberately have no
        persistence checkpoint.
        """

        execution_result = (
            context.execution_result
        )

        if execution_result is None:
            raise TradingDayEntryRuntimeError(
                "cancelled entry persistence requires "
                "execution result"
            )

        execution_service = (
            self._entry_adapter
            .execution_service
        )

        provider = getattr(
            execution_service,
            "broker_provider",
            None,
        )

        if not isinstance(
            provider,
            DurableEntryBrokerExecutionProvider,
        ):
            return

        lifecycle_snapshot = (
            execution_service
            .order_state_machine
            .snapshot(
                context.intent.intent_id
            )
        )

        provider.persistence.persist_cancelled_entry_order(
            intent=context.intent,
            result=execution_result,
            broker_snapshot=snapshot,
            lifecycle_snapshot=(
                lifecycle_snapshot
            ),
        )


    def _abort_and_store(
        self,
        *,
        signal_runtime_result:
            TradingDaySignalRuntimeResult,
        reason: TradingDayEntryRuntimeReason,
        sizing: EntryOrderSizing | None = None,
        daily_risk: DailyRiskSnapshot | None = None,
        exposure_risk:
            ExposureRiskDecision | None = None,
        account_result:
            AccountGatedEntryResult | None = None,
        execution_result:
            ExecutionServiceResult | None = None,
        message: str | None = None,
    ) -> TradingDayEntryRuntimeResult:
        signal = (
            signal_runtime_result.signal
        )

        if signal is None:
            raise TradingDayEntryRuntimeError(
                "cannot abort missing signal"
            )

        self._release_signal_lock(
            signal
        )

        result = (
            TradingDayEntryRuntimeResult(
                signal_runtime_result=(
                    signal_runtime_result
                ),
                reason=reason,
                sizing=sizing,
                daily_risk=daily_risk,
                exposure_risk=(
                    exposure_risk
                ),
                account_result=(
                    account_result
                ),
                execution_result=(
                    execution_result
                ),
                message=message,
            )
        )

        self._results[
            signal.signal_id.value
        ] = result

        return result

    def _release_signal_lock(
        self,
        signal: TradingSignal,
    ) -> None:
        released = (
            self._signal_runtime
            .signal_engine
            .release_signal_lock(
                signal
            )
        )

        if not released:
            raise TradingDayEntryRuntimeError(
                "accepted signal no longer owns "
                "its M04 level lock"
            )

    # --------------------------------------------------------
    # Identity / composition
    # --------------------------------------------------------

    def _resolve_levels(
        self,
        *,
        signal: TradingSignal,
        selected_option: SelectedOption,
    ):
        if (
            selected_option.security_id
            == self._signal_runtime
            .selected_call
            .security_id
        ):
            levels = (
                self._level_preparation
                .call_levels
            )

        elif (
            selected_option.security_id
            == self._signal_runtime
            .selected_put
            .security_id
        ):
            levels = (
                self._level_preparation
                .put_levels
            )

        else:
            raise TradingDayEntryRuntimeError(
                "signal selected option is not one "
                "of the fixed morning contracts"
            )

        if (
            levels.instrument_security_id
            != selected_option.security_id
        ):
            raise TradingDayEntryRuntimeError(
                "KS levels security ID does not match "
                "selected option"
            )

        if (
            levels.instrument_symbol
            != selected_option.symbol
        ):
            raise TradingDayEntryRuntimeError(
                "KS levels symbol does not match "
                "selected option"
            )

        if (
            levels.trading_date
            != signal.trading_date
        ):
            raise TradingDayEntryRuntimeError(
                "KS levels trading date does not match "
                "signal trading date"
            )

        return levels

    def _validate_signal_identity(
        self,
        *,
        signal: TradingSignal,
        selected_option: SelectedOption,
    ) -> None:
        if (
            signal.instrument_security_id
            != selected_option.security_id
        ):
            raise TradingDayEntryRuntimeError(
                "signal security ID does not match "
                "selected option"
            )

        if (
            signal.instrument_symbol
            != selected_option.symbol
        ):
            raise TradingDayEntryRuntimeError(
                "signal symbol does not match "
                "selected option"
            )

        if (
            signal.direction.value
            != selected_option
            .option_type.value
        ):
            raise TradingDayEntryRuntimeError(
                "signal direction does not match "
                "selected option type"
            )

    @staticmethod
    def _validate_intent_identity(
        *,
        intent: OrderIntent,
        signal: TradingSignal,
        selected_option: SelectedOption,
    ) -> None:
        if (
            intent.signal.signal_id
            != signal.signal_id
        ):
            raise TradingDayEntryRuntimeError(
                "entry intent signal identity mismatch"
            )

        if (
            intent.selected_option.security_id
            != selected_option.security_id
        ):
            raise TradingDayEntryRuntimeError(
                "entry intent security ID mismatch"
            )

        if (
            intent.selected_option.symbol
            != selected_option.symbol
        ):
            raise TradingDayEntryRuntimeError(
                "entry intent symbol mismatch"
            )

    def _broker_boundary_crossed(
        self,
        signal: TradingSignal,
    ) -> bool:
        """
        Fail-closed fallback for unexpected exceptions.

        SUBMITTED / COMPLETED means M06 crossed the LIVE broker
        safety boundary and M04 ownership must remain locked.
        """

        try:
            guard = (
                self._entry_adapter
                .execution_service
                .idempotency_guard
            )

            record = guard.get(
                IdempotencyKey.from_signal_id(
                    signal.signal_id
                )
            )

        except Exception:
            # Phoenix cannot prove that the LIVE broker boundary
            # was not crossed when M06 idempotency inspection
            # itself fails.
            #
            # Retain the M04 signal lock and require explicit
            # reconciliation rather than risking a duplicate BUY.
            return True

        if record is None:
            return False

        return record.state in {
            IdempotencyState.SUBMITTED,
            IdempotencyState.COMPLETED,
        }

    def _validate_composition(
        self,
    ) -> None:
        if (
            self._account_gate
            .entry_execution
            is not self._entry_adapter
        ):
            raise ValueError(
                "M09 account gate must delegate to "
                "the exact supplied M06 entry adapter"
            )

        registry = (
            self._position_initializer
            .registry
        )

        if (
            self._exposure_policy.registry
            is not registry
        ):
            raise ValueError(
                "exposure policy and position initializer "
                "must share exact PositionRegistry"
            )

        if (
            self._daily_risk_manager.registry
            is not registry
        ):
            raise ValueError(
                "daily risk manager and position initializer "
                "must share exact PositionRegistry"
            )

        if not self._level_preparation.is_ready:
            raise ValueError(
                "level preparation must be ready"
            )

        if (
            self._level_preparation.selected_call
            != self._signal_runtime.selected_call
        ):
            raise ValueError(
                "level preparation CALL does not match "
                "signal runtime CALL"
            )

        if (
            self._level_preparation.selected_put
            != self._signal_runtime.selected_put
        ):
            raise ValueError(
                "level preparation PUT does not match "
                "signal runtime PUT"
            )

        self._validate_prepared_side(
            selected_option=(
                self._signal_runtime
                .selected_call
            ),
            levels=(
                self._level_preparation
                .call_levels
            ),
        )

        self._validate_prepared_side(
            selected_option=(
                self._signal_runtime
                .selected_put
            ),
            levels=(
                self._level_preparation
                .put_levels
            ),
        )

    @staticmethod
    def _validate_prepared_side(
        *,
        selected_option: SelectedOption,
        levels,
    ) -> None:
        if (
            levels.instrument_security_id
            != selected_option.security_id
        ):
            raise ValueError(
                "prepared KS security ID does not "
                "match selected option"
            )

        if (
            levels.instrument_symbol
            != selected_option.symbol
        ):
            raise ValueError(
                "prepared KS symbol does not "
                "match selected option"
            )

    @staticmethod
    def _normalize_signal_id(
        signal_id: str,
    ) -> str:
        if type(signal_id) is not str:
            raise TypeError(
                "signal_id must be str"
            )

        normalized = signal_id.strip()

        if not normalized:
            raise ValueError(
                "signal_id cannot be empty"
            )

        return normalized


__all__ += [
    "TradingDayEntryReconciliationContext",
    "TradingDayEntryRuntimeCoordinator",
    "TradingDayEntryRuntimeError",
    "TradingDayEntryRuntimeReason",
    "TradingDayEntryRuntimeResult",
]


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayTickRuntimeResult:
    """
    Result of processing one normalized selected-option tick
    through the M10 application runtime.

    One market tick may cause LevelMonitor to report multiple
    K-level crossings when price gaps across K5/K6/K7.

    Phoenix intentionally permits at most ONE of those events to
    proceed toward M04/M06 from the same market tick.
    """

    tick: MarketTick

    events: tuple[
        LevelEvent,
        ...
    ]

    selected_event: LevelEvent | None

    signal_runtime_result: (
        TradingDaySignalRuntimeResult | None
    )

    entry_runtime_result: (
        TradingDayEntryRuntimeResult | None
    )

    @property
    def has_level_event(
        self,
    ) -> bool:
        return self.selected_event is not None

    @property
    def signal_created(
        self,
    ) -> bool:
        return (
            self.signal_runtime_result is not None
            and self.signal_runtime_result.created
        )

    @property
    def position_opened(
        self,
    ) -> bool:
        return (
            self.entry_runtime_result is not None
            and self.entry_runtime_result.position_opened
        )


class TradingDayTickRuntimeError(
    RuntimeError
):
    """
    T14 could not safely compose tick monitoring with the
    signal/entry runtime.
    """


class TradingDayTickRuntimeCoordinator:
    """
    Final T14 application boundary for one normalized market tick.

    Ownership remains unchanged:

        TradingDayTickMonitoringCoordinator
            MarketTick -> tuple[LevelEvent, ...]

        TradingDaySignalRuntimeCoordinator
            selected LevelEvent -> M04

        TradingDayEntryRuntimeCoordinator
            accepted M04 signal -> M07/M09/M06

    Same-tick multi-level rule:

        - one market tick can never fan out into multiple BUY
          submissions;

        - for CROSSED_UP, the first traversed price level is the
          LOWEST crossed level;

        - for CROSSED_DOWN, the first traversed price level is the
          HIGHEST crossed level;

        - a single TOUCHED event may proceed;

        - ambiguous/malformed multi-event batches fail closed.

    Events not selected from the same tick are deliberately not
    replayed. They may become eligible only after a later genuine
    market interaction/re-cross reported by LevelMonitor.
    """

    def __init__(
        self,
        *,
        tick_monitor:
            TradingDayTickMonitoringCoordinator,
        signal_runtime:
            TradingDaySignalRuntimeCoordinator,
        entry_runtime:
            TradingDayEntryRuntimeCoordinator,
    ) -> None:
        self._tick_monitor = tick_monitor
        self._signal_runtime = signal_runtime
        self._entry_runtime = entry_runtime

        self._validate_composition()

    @property
    def tick_monitor(
        self,
    ) -> TradingDayTickMonitoringCoordinator:
        return self._tick_monitor

    @property
    def signal_runtime(
        self,
    ) -> TradingDaySignalRuntimeCoordinator:
        return self._signal_runtime

    @property
    def entry_runtime(
        self,
    ) -> TradingDayEntryRuntimeCoordinator:
        return self._entry_runtime

    def process_tick(
        self,
        tick: MarketTick,
        *,
        dry_run: bool,
    ) -> TradingDayTickRuntimeResult:
        """
        Process exactly one normalized market tick.

        At most one LevelEvent is allowed to cross the application
        boundary into M04/M06 for this tick.
        """

        if not isinstance(
            tick,
            MarketTick,
        ):
            raise TypeError(
                "tick must be a MarketTick"
            )

        if type(dry_run) is not bool:
            raise TypeError(
                "dry_run must be bool"
            )

        events = (
            self._tick_monitor
            .process_tick(
                tick
            )
        )

        self._validate_event_batch(
            tick=tick,
            events=events,
        )

        if not events:
            return TradingDayTickRuntimeResult(
                tick=tick,
                events=(),
                selected_event=None,
                signal_runtime_result=None,
                entry_runtime_result=None,
            )

        selected_event = (
            self._select_single_event(
                events
            )
        )

        signal_result = (
            self._signal_runtime
            .process_event(
                selected_event
            )
        )

        if not isinstance(
            signal_result,
            TradingDaySignalRuntimeResult,
        ):
            raise TradingDayTickRuntimeError(
                "signal runtime returned invalid result"
            )

        entry_result = (
            self._entry_runtime
            .process_signal_result(
                signal_result,
                dry_run=dry_run,
                requested_at=tick.timestamp,
            )
        )

        if not isinstance(
            entry_result,
            TradingDayEntryRuntimeResult,
        ):
            raise TradingDayTickRuntimeError(
                "entry runtime returned invalid result"
            )

        if (
            entry_result.signal_runtime_result
            is not signal_result
        ):
            raise TradingDayTickRuntimeError(
                "entry runtime result does not belong "
                "to processed signal result"
            )

        return TradingDayTickRuntimeResult(
            tick=tick,
            events=events,
            selected_event=selected_event,
            signal_runtime_result=signal_result,
            entry_runtime_result=entry_result,
        )

    def _validate_composition(
        self,
    ) -> None:
        if (
            self._entry_runtime.signal_runtime
            is not self._signal_runtime
        ):
            raise ValueError(
                "entry runtime must own the exact "
                "signal runtime"
            )

        monitor_scheduler = (
            self._tick_monitor.scheduler
        )

        signal_scheduler = (
            self._signal_runtime
            .entry_gate
            .scheduler
        )

        if (
            monitor_scheduler
            is not signal_scheduler
        ):
            raise ValueError(
                "tick monitor and signal runtime must "
                "share the exact TradingDayScheduler"
            )

        preparation = (
            self._tick_monitor.preparation
        )

        if (
            preparation.selected_call
            != self._signal_runtime.selected_call
        ):
            raise ValueError(
                "tick monitor selected CALL does not "
                "match signal runtime selected CALL"
            )

        if (
            preparation.selected_put
            != self._signal_runtime.selected_put
        ):
            raise ValueError(
                "tick monitor selected PUT does not "
                "match signal runtime selected PUT"
            )

    @staticmethod
    def _validate_event_batch(
        *,
        tick: MarketTick,
        events: tuple[
            LevelEvent,
            ...
        ],
    ) -> None:
        if type(events) is not tuple:
            raise TradingDayTickRuntimeError(
                "tick monitor must return tuple[LevelEvent, ...]"
            )

        seen_levels = set()

        for event in events:
            if not isinstance(
                event,
                LevelEvent,
            ):
                raise TradingDayTickRuntimeError(
                    "tick monitor returned non-LevelEvent"
                )

            if (
                event.instrument_security_id
                != tick.security_id
            ):
                raise TradingDayTickRuntimeError(
                    "level event security ID does not "
                    "match source tick"
                )

            if (
                event.instrument_symbol
                != tick.symbol
            ):
                raise TradingDayTickRuntimeError(
                    "level event symbol does not "
                    "match source tick"
                )

            if (
                event.trading_date
                != tick.timestamp.date()
            ):
                raise TradingDayTickRuntimeError(
                    "level event trading date does not "
                    "match source tick"
                )

            if (
                event.timestamp
                != tick.timestamp
            ):
                raise TradingDayTickRuntimeError(
                    "level event timestamp does not "
                    "match source tick"
                )

            if (
                event.market_price
                != tick.ltp
            ):
                raise TradingDayTickRuntimeError(
                    "level event market price does not "
                    "match source tick"
                )

            if event.level in seen_levels:
                raise TradingDayTickRuntimeError(
                    "tick monitor returned duplicate "
                    "level event"
                )

            seen_levels.add(
                event.level
            )

    @staticmethod
    def _select_single_event(
        events: tuple[
            LevelEvent,
            ...
        ],
    ) -> LevelEvent:
        if not events:
            raise ValueError(
                "cannot select from empty event batch"
            )

        if len(events) == 1:
            return events[0]

        event_types = {
            event.event_type
            for event in events
        }

        if event_types == {
            LevelEventType.CROSSED_UP
        }:
            return min(
                events,
                key=lambda event:
                    event.level_price,
            )

        if event_types == {
            LevelEventType.CROSSED_DOWN
        }:
            return max(
                events,
                key=lambda event:
                    event.level_price,
            )

        raise TradingDayTickRuntimeError(
            "ambiguous same-tick multi-level event batch"
        )


__all__ += [
    "TradingDayTickRuntimeCoordinator",
    "TradingDayTickRuntimeError",
    "TradingDayTickRuntimeResult",
]


class TradingDayMarketIngressError(
    RuntimeError
):
    """
    T14 raw-market ingress could not safely hand a normalized
    market tick to the trading-day runtime.
    """


class TradingDayMarketIngressHandler:
    """
    Thin M10 application boundary between the existing M02 raw
    market-message path and TradingDayTickRuntimeCoordinator.

    Flow:

        raw Dhan message
            ->
        TickProcessor.process()
            ->
        MarketTick | None
            ->
        TradingDayTickRuntimeCoordinator.process_tick()

    Ownership remains unchanged:

        M02:
            raw-message normalization and MarketDataService
            publication.

        M10 application runtime:
            selected-option monitoring, M04 signal processing,
            risk/account gating and M06 entry execution.

    This handler deliberately does not publish MARKET_TICK onto
    RuntimeEventBus. RuntimeEventAuditSubscriber may subscribe to
    every RuntimeEventType, so high-frequency market ticks must
    not become durable audit events merely to reach M10.

    MessageDispatcher expects Callable[[Any], None], therefore
    this handler intentionally returns None. Trading-runtime
    failures are not swallowed; they propagate to the existing
    Dhan adapter boundary so market/runtime failures remain
    visible and fail closed.
    """

    def __init__(
        self,
        *,
        tick_processor: TickProcessor,
        tick_runtime:
            TradingDayTickRuntimeCoordinator,
        dry_run: bool,
    ) -> None:
        if not isinstance(
            tick_processor,
            TickProcessor,
        ):
            raise TypeError(
                "tick_processor must be a TickProcessor"
            )

        if not isinstance(
            tick_runtime,
            TradingDayTickRuntimeCoordinator,
        ):
            raise TypeError(
                "tick_runtime must be a "
                "TradingDayTickRuntimeCoordinator"
            )

        if type(dry_run) is not bool:
            raise TypeError(
                "dry_run must be bool"
            )

        self._tick_processor = tick_processor
        self._tick_runtime = tick_runtime
        self._dry_run = dry_run

    @property
    def tick_processor(
        self,
    ) -> TickProcessor:
        return self._tick_processor

    @property
    def tick_runtime(
        self,
    ) -> TradingDayTickRuntimeCoordinator:
        return self._tick_runtime

    @property
    def dry_run(
        self,
    ) -> bool:
        return self._dry_run

    def __call__(
        self,
        message: Any,
    ) -> None:
        """
        Normalize and route one raw market-feed message.

        Non-price/control packets are routine M02 traffic and
        terminate normally when TickProcessor returns None.
        """

        tick = self._tick_processor.process(
            message
        )

        if tick is None:
            return

        if not isinstance(
            tick,
            MarketTick,
        ):
            raise TradingDayMarketIngressError(
                "TickProcessor returned invalid "
                "market tick result"
            )

        result = (
            self._tick_runtime
            .process_tick(
                tick,
                dry_run=self._dry_run,
            )
        )

        if not isinstance(
            result,
            TradingDayTickRuntimeResult,
        ):
            raise TradingDayMarketIngressError(
                "tick runtime returned invalid result"
            )


__all__ += [
    "TradingDayMarketIngressError",
    "TradingDayMarketIngressHandler",
]


class TradingDayCloseReadinessProvider:
    """
    T14 application-level implementation of M10's
    TradingDayCloseReadinessPort.

    Closure requires agreement across both application/runtime
    state and authoritative broker-wide account state.

    Local truth:
        - M07 PositionRegistry.open_positions()
        - unresolved LIVE entry contexts retained by
          TradingDayEntryRuntimeCoordinator

    Broker truth:
        - Dhan account positions with non-zero netQty
        - Dhan day orders whose state is not safely terminal

    Counts use max(local, broker), not addition. The same Phoenix
    position/order normally exists in both domains and must not be
    double-counted. For M10 closure, the safety requirement is
    simply that both views prove zero.

    Any broker or local inspection failure propagates. The
    TradingDayEndOfDayCoordinator will therefore keep Phoenix in
    EXIT_ONLY rather than transitioning CLOSED without proof.
    """

    def __init__(
        self,
        *,
        entry_runtime:
            TradingDayEntryRuntimeCoordinator,
        account_adapter:
            DhanAccountAdapter,
        durable_order_repository:
            SQLAlchemyOrderRepository
            | None = None,
        runtime_id: str | None = None,
    ) -> None:
        if not isinstance(
            entry_runtime,
            TradingDayEntryRuntimeCoordinator,
        ):
            raise TypeError(
                "entry_runtime must be a "
                "TradingDayEntryRuntimeCoordinator"
            )

        if not isinstance(
            account_adapter,
            DhanAccountAdapter,
        ):
            raise TypeError(
                "account_adapter must be a "
                "DhanAccountAdapter"
            )

        self._entry_runtime = (
            entry_runtime
        )

        self._account_adapter = (
            account_adapter
        )

        if (
            durable_order_repository
            is None
        ) != (
            runtime_id is None
        ):
            raise ValueError(
                "durable_order_repository and runtime_id "
                "must be supplied together"
            )

        normalized_runtime_id = None

        if runtime_id is not None:
            normalized_runtime_id = (
                runtime_id.strip()
            )

            if not normalized_runtime_id:
                raise ValueError(
                    "runtime_id cannot be empty"
                )

        self._durable_order_repository = (
            durable_order_repository
        )

        self._runtime_id = (
            normalized_runtime_id
        )

    @property
    def entry_runtime(
        self,
    ) -> TradingDayEntryRuntimeCoordinator:
        return self._entry_runtime

    @property
    def account_adapter(
        self,
    ) -> DhanAccountAdapter:
        return self._account_adapter

    @property
    def durable_order_repository(
        self,
    ) -> SQLAlchemyOrderRepository | None:
        return self._durable_order_repository

    @property
    def runtime_id(
        self,
    ) -> str | None:
        return self._runtime_id

    def evaluate_close_readiness(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayCloseReadiness:
        if type(evaluated_at) is not datetime:
            raise TypeError(
                "evaluated_at must be a datetime"
            )

        local_open_positions = len(
            self._entry_runtime
            .position_registry
            .open_positions()
        )

        entry_unresolved_orders = (
            self._entry_runtime
            .pending_count
        )

        durable_unresolved_orders = 0

        if (
            self._durable_order_repository
            is not None
        ):
            assert self._runtime_id is not None

            durable_unresolved_orders = len(
                self._durable_order_repository
                .list_open_orders(
                    self._runtime_id
                )
            )

        local_unresolved_orders = max(
            entry_unresolved_orders,
            durable_unresolved_orders,
        )

        self._validate_count(
            local_open_positions,
            name=(
                "local open position count"
            ),
        )

        self._validate_count(
            local_unresolved_orders,
            name=(
                "local unresolved order count"
            ),
        )

        broker_open_positions = (
            self._account_adapter
            .fetch_open_position_count(
                broker=(
                    self._account_adapter
                    .broker
                ),
                account_id=(
                    self._account_adapter
                    .account_id
                ),
                requested_at=(
                    evaluated_at
                ),
            )
        )

        broker_unresolved_orders = (
            self._account_adapter
            .fetch_unresolved_order_count(
                broker=(
                    self._account_adapter
                    .broker
                ),
                account_id=(
                    self._account_adapter
                    .account_id
                ),
                requested_at=(
                    evaluated_at
                ),
            )
        )

        self._validate_count(
            broker_open_positions,
            name=(
                "broker open position count"
            ),
        )

        self._validate_count(
            broker_unresolved_orders,
            name=(
                "broker unresolved order count"
            ),
        )

        return TradingDayCloseReadiness(
            open_position_count=max(
                local_open_positions,
                broker_open_positions,
            ),
            unresolved_order_count=max(
                local_unresolved_orders,
                broker_unresolved_orders,
            ),
        )

    @staticmethod
    def _validate_count(
        value: int,
        *,
        name: str,
    ) -> None:
        if (
            type(value) is not int
            or value < 0
        ):
            raise RuntimeError(
                f"{name} must be a "
                "non-negative int"
            )


__all__ += [
    "TradingDayCloseReadinessProvider",
]


# ============================================================
# M10 15:15 force-exit execution runtime
# ============================================================

from src.database.exit_durability import (
    DurableExitExecutionProvider,
    SQLAlchemyExitPersistenceService,
)
from src.database.schema import (
    OrderRecord,
)
from src.execution.execution_types import (
    BrokerOrderReference,
)
from src.execution.exit_execution_provider import (
    ExitOrderIntent,
    ExitOrderIntentId,
    ExitTransactionType,
)
from src.execution.exit_execution_service import (
    ExitExecutionServiceResult,
)
from src.execution.exit_reconciliation_service import (
    ExitReconciliationDecision,
    ExitReconciliationService,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
    IdempotencyKey,
    IdempotencyState,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitReason,
)
from src.risk.force_exit_coordinator import (
    ForceExitAction,
    ForceExitInstruction,
    ForceExitReason,
)
from src.risk.m06_exit_integration_service import (
    M07ExitIntegrationStatus,
    M07ToM06ExitIntegrationService,
)
from src.risk.position_exit_decision_engine import (
    PositionExitDecision,
    PositionExitDecisionStatus,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPositionState,
    RiskTriggerType,
)
from src.services.scheduler import (
    TradingDayForceExitCoordinator,
    TradingDayForceExitResult,
)


class TradingDayForceExitRuntimeStatus(
    str,
    Enum,
):
    """
    Result of executing one M10 force-exit instruction.
    """

    NOT_DUE = "NOT_DUE"

    NO_ACTION = "NO_ACTION"

    DRY_RUN_PENDING = "DRY_RUN_PENDING"

    LIVE_EXIT_ACTIVE = "LIVE_EXIT_ACTIVE"

    REPLACEMENT_ACTIVE = "REPLACEMENT_ACTIVE"

    POSITION_CLOSED = "POSITION_CLOSED"

    RETRY_REQUIRED = "RETRY_REQUIRED"

    RECONCILIATION_REQUIRED = (
        "RECONCILIATION_REQUIRED"
    )

    FAILED_CLOSED = "FAILED_CLOSED"


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayForceExitInstructionResult:
    """
    Application result for one M07 ForceExitInstruction.
    """

    instruction: ForceExitInstruction

    status: TradingDayForceExitRuntimeStatus

    position: ManagedPosition

    exit_intent_id: str | None = None

    broker_order_id: str | None = None

    message: str | None = None


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayForceExitRuntimeResult:
    """
    Result of one complete M10 15:15 execution cycle.
    """

    coordination: TradingDayForceExitResult

    instruction_results: tuple[
        TradingDayForceExitInstructionResult,
        ...
    ]

    evaluated_at: datetime


class TradingDayForceExitRuntimeCoordinator:
    """
    Executes M10's 15:15 M07 force-exit instructions.

    Safety ordering:

        TradingDayForceExitCoordinator
            ->
        M10 EXIT_ONLY
            ->
        ForceExitInstruction
            ->
        M07/M06 execution or reconciliation
            ->
        durable broker fill ledger
            ->
        M07 PositionLifecycleManager
            ->
        durable PositionRecord
            ->
        terminal SELL OrderRecord
            ->
        replacement SELL only when previous SELL is proven dead

    This coordinator does not implement broker payload logic.
    """

    _ACTIVE_BROKER_STATUSES = frozenset(
        {
            BrokerOrderStatus.PENDING,
            BrokerOrderStatus.OPEN,
            BrokerOrderStatus.PARTIALLY_FILLED,
        }
    )

    def __init__(
        self,
        *,
        trading_day_force_exit:
            TradingDayForceExitCoordinator,
        exit_integration:
            M07ToM06ExitIntegrationService,
        exit_reconciliation:
            ExitReconciliationService,
        exit_persistence:
            SQLAlchemyExitPersistenceService,
        durable_exit_provider:
            DurableExitExecutionProvider,
        position_lifecycle_manager:
            PositionLifecycleManager,
        position_registry:
            PositionRegistry,
        order_repository:
            SQLAlchemyOrderRepository,
        duplicate_guard:
            DuplicateOrderGuard,
        runtime_id: str,
        execution_mode: ExecutionMode,
    ) -> None:
        normalized_runtime_id = (
            runtime_id.strip()
        )

        if not normalized_runtime_id:
            raise ValueError(
                "runtime_id cannot be empty"
            )

        if not isinstance(
            execution_mode,
            ExecutionMode,
        ):
            raise TypeError(
                "execution_mode must be ExecutionMode"
            )

        self._trading_day_force_exit = (
            trading_day_force_exit
        )

        self._exit_integration = (
            exit_integration
        )

        self._exit_reconciliation = (
            exit_reconciliation
        )

        self._exit_persistence = (
            exit_persistence
        )

        self._durable_exit_provider = (
            durable_exit_provider
        )

        self._position_lifecycle_manager = (
            position_lifecycle_manager
        )

        self._position_registry = (
            position_registry
        )

        self._order_repository = (
            order_repository
        )

        self._duplicate_guard = (
            duplicate_guard
        )

        self._runtime_id = (
            normalized_runtime_id
        )

        self._execution_mode = (
            execution_mode
        )

    # ========================================================
    # Exact composition ownership
    # ========================================================

    @property
    def trading_day_force_exit(
        self,
    ) -> TradingDayForceExitCoordinator:
        return self._trading_day_force_exit

    @property
    def exit_integration(
        self,
    ) -> M07ToM06ExitIntegrationService:
        return self._exit_integration

    @property
    def exit_reconciliation(
        self,
    ) -> ExitReconciliationService:
        return self._exit_reconciliation

    @property
    def exit_persistence(
        self,
    ) -> SQLAlchemyExitPersistenceService:
        return self._exit_persistence

    @property
    def durable_exit_provider(
        self,
    ) -> DurableExitExecutionProvider:
        return self._durable_exit_provider

    @property
    def position_lifecycle_manager(
        self,
    ) -> PositionLifecycleManager:
        return self._position_lifecycle_manager

    @property
    def position_registry(
        self,
    ) -> PositionRegistry:
        return self._position_registry

    @property
    def order_repository(
        self,
    ) -> SQLAlchemyOrderRepository:
        return self._order_repository

    @property
    def duplicate_guard(
        self,
    ) -> DuplicateOrderGuard:
        return self._duplicate_guard

    @property
    def runtime_id(
        self,
    ) -> str:
        return self._runtime_id

    @property
    def execution_mode(
        self,
    ) -> ExecutionMode:
        return self._execution_mode

    # ========================================================
    # Public 15:15 cycle
    # ========================================================

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayForceExitRuntimeResult:
        """
        Coordinate M10 first, then execute every resulting M07
        instruction.

        One position failure does not prevent evaluation of the
        remaining positions.

        Any uncertain open position is moved to
        RECONCILIATION_REQUIRED and persisted fail-closed.
        """

        coordination = (
            self._trading_day_force_exit
            .coordinate(
                evaluated_at=evaluated_at
            )
        )

        if not coordination.force_exit_due:
            return TradingDayForceExitRuntimeResult(
                coordination=coordination,
                instruction_results=(),
                evaluated_at=evaluated_at,
            )

        batch = coordination.batch

        if batch is None:
            raise RuntimeError(
                "force-exit due result requires batch"
            )

        results: list[
            TradingDayForceExitInstructionResult
        ] = []

        for instruction in batch.instructions:
            try:
                result = (
                    self._process_instruction(
                        instruction=instruction,
                        evaluated_at=evaluated_at,
                    )
                )

            except Exception as exc:
                result = self._fail_closed(
                    instruction=instruction,
                    changed_at=evaluated_at,
                    message=(
                        "force-exit runtime failure: "
                        f"{exc}"
                    ),
                )

            results.append(
                result
            )

        return TradingDayForceExitRuntimeResult(
            coordination=coordination,
            instruction_results=tuple(
                results
            ),
            evaluated_at=evaluated_at,
        )


    def liquidate_open_positions(
        self,
        *,
        evaluated_at: datetime,
    ) -> tuple[
        TradingDayForceExitInstructionResult,
        ...,
    ]:
        """
        Immediately liquidate all currently open exposure for an
        operator-requested M10 manual stop.

        Unlike evaluate(), this method deliberately does NOT call
        TradingDayForceExitCoordinator and therefore has no 15:15
        time gate.

        Existing unresolved SELLs are reconciled through the same
        durable M06 path instead of generating duplicate SELLs.

        One position failure does not prevent the remaining
        positions from being processed.
        """

        if type(evaluated_at) is not datetime:
            raise TypeError(
                "evaluated_at must be a datetime"
            )

        positions = tuple(
            sorted(
                self._position_registry
                .open_positions(),
                key=lambda position: (
                    position.position_id.value
                ),
            )
        )

        results: list[
            TradingDayForceExitInstructionResult
        ] = []

        for position in positions:

            if (
                position.state
                is ManagedPositionState.EXIT_PENDING
            ):
                action = (
                    ForceExitAction
                    .RECONCILE_EXISTING_EXIT
                )

                reason = (
                    ForceExitReason
                    .EXIT_ALREADY_PENDING
                )

            elif (
                position.state
                is ManagedPositionState
                .RECONCILIATION_REQUIRED
            ):
                action = (
                    ForceExitAction
                    .RECONCILE_EXISTING_EXIT
                )

                reason = (
                    ForceExitReason
                    .RECONCILIATION_ALREADY_REQUIRED
                )

            elif (
                position.state
                is ManagedPositionState
                .PARTIALLY_EXITED
            ):
                action = (
                    ForceExitAction.NEW_FORCE_EXIT
                )

                reason = (
                    ForceExitReason.PARTIAL_POSITION
                )

            else:
                action = (
                    ForceExitAction.NEW_FORCE_EXIT
                )

                reason = (
                    ForceExitReason.OPEN_POSITION
                )

            instruction = ForceExitInstruction(
                position_id=(
                    position.position_id
                ),
                action=action,
                reason=reason,
                trigger=RiskTriggerType.MANUAL,
                quantity=(
                    position.open_quantity
                ),
                evaluated_at=evaluated_at,
            )

            try:
                result = self._process_instruction(
                    instruction=instruction,
                    evaluated_at=evaluated_at,
                )

            except Exception as exc:
                result = self._fail_closed(
                    instruction=instruction,
                    changed_at=evaluated_at,
                    message=(
                        "manual liquidation runtime failure: "
                        f"{exc}"
                    ),
                )

            results.append(
                result
            )

        return tuple(
            results
        )

    # ========================================================
    # Instruction routing
    # ========================================================

    def _process_instruction(
        self,
        *,
        instruction: ForceExitInstruction,
        evaluated_at: datetime,
    ) -> TradingDayForceExitInstructionResult:
        position = (
            self._position_registry.require(
                instruction.position_id
            )
        )

        if (
            instruction.action
            is ForceExitAction.NONE
        ):
            return (
                TradingDayForceExitInstructionResult(
                    instruction=instruction,
                    status=(
                        TradingDayForceExitRuntimeStatus
                        .NO_ACTION
                    ),
                    position=position,
                )
            )

        if (
            instruction.action
            is ForceExitAction.NEW_FORCE_EXIT
        ):
            return self._submit_force_exit(
                instruction=instruction,
                quantity=instruction.quantity,
                evaluated_at=evaluated_at,
                replacement=False,
            )

        if (
            instruction.action
            is ForceExitAction
            .RECONCILE_EXISTING_EXIT
        ):
            return self._reconcile_existing_exit(
                instruction=instruction,
                evaluated_at=evaluated_at,
            )

        raise RuntimeError(
            "unsupported force-exit instruction"
        )

    # ========================================================
    # NEW_FORCE_EXIT
    # ========================================================

    def _submit_force_exit(
        self,
        *,
        instruction: ForceExitInstruction,
        quantity: int,
        evaluated_at: datetime,
        replacement: bool,
    ) -> TradingDayForceExitInstructionResult:
        position = (
            self._position_registry.require(
                instruction.position_id
            )
        )

        if quantity <= 0:
            raise ValueError(
                "force-exit quantity must be positive"
            )

        if quantity != position.open_quantity:
            raise ValueError(
                "force-exit quantity must equal "
                "current open quantity"
            )

        if (
            instruction.trigger
            not in {
                RiskTriggerType.FORCE_EXIT,
                RiskTriggerType.MANUAL,
            }
        ):
            raise ValueError(
                "runtime SELL requires FORCE_EXIT "
                "or MANUAL trigger"
            )

        operation_label = (
            "manual liquidation"
            if (
                instruction.trigger
                is RiskTriggerType.MANUAL
            )
            else "force-exit"
        )

        decision_message = (
            "M10 operator manual liquidation"
            if (
                instruction.trigger
                is RiskTriggerType.MANUAL
            )
            else (
                "M10 mandatory 15:15 "
                "force exit"
            )
        )

        decision = PositionExitDecision(
            status=(
                PositionExitDecisionStatus
                .EXIT_REQUIRED
            ),
            position_id=(
                instruction.position_id
            ),
            trigger=instruction.trigger,
            quantity=quantity,
            decided_at=evaluated_at,
            message=decision_message,
        )

        integration = (
            self._exit_integration
            .execute_decision(
                decision=decision,
                execution_mode=(
                    self._execution_mode
                ),
                requested_at=evaluated_at,
            )
        )

        # M07 moves to EXIT_PENDING before M06 submission.
        # Make that lifecycle state durable immediately.
        self._exit_persistence\
            .persist_managed_position_state(
                managed_position=(
                    integration.position
                )
            )

        # ----------------------------------------------------
        # DRY_RUN deliberately has no durable broker SELL.
        # ----------------------------------------------------

        if (
            self._execution_mode
            is ExecutionMode.DRY_RUN
        ):
            service_result = (
                integration.execution_result
            )

            intent_id = None

            if isinstance(
                service_result,
                ExitExecutionServiceResult,
            ):
                if service_result.intent is not None:
                    intent_id = (
                        service_result
                        .intent
                        .intent_id
                        .value
                    )

            return (
                TradingDayForceExitInstructionResult(
                    instruction=instruction,
                    status=(
                        TradingDayForceExitRuntimeStatus
                        .DRY_RUN_PENDING
                    ),
                    position=integration.position,
                    exit_intent_id=intent_id,
                    message=(
                        integration.message
                    ),
                )
            )

        # ----------------------------------------------------
        # Conservative M07/M06 failure
        # ----------------------------------------------------

        if (
            integration.status
            is M07ExitIntegrationStatus
            .RECONCILIATION_REQUIRED
        ):
            return (
                TradingDayForceExitInstructionResult(
                    instruction=instruction,
                    status=(
                        TradingDayForceExitRuntimeStatus
                        .RECONCILIATION_REQUIRED
                    ),
                    position=integration.position,
                    message=integration.message,
                )
            )

        if (
            integration.status
            is not M07ExitIntegrationStatus.SUBMITTED
        ):
            raise RuntimeError(
                f"{operation_label} integration did not "
                "submit SELL"
            )

        service_result = (
            integration.execution_result
        )

        if not isinstance(
            service_result,
            ExitExecutionServiceResult,
        ):
            raise RuntimeError(
                "M07 exit integration returned "
                "unexpected M06 result"
            )

        intent = service_result.intent

        broker_result = (
            service_result.execution_result
        )

        if (
            not service_result.accepted
            or intent is None
            or broker_result is None
        ):
            return self._mark_reconciliation_required(
                instruction=instruction,
                changed_at=evaluated_at,
                message=(
                    service_result.message
                    or "LIVE SELL was not proven accepted"
                ),
            )

        reference = (
            broker_result.broker_reference
        )

        if reference is None:
            return self._mark_reconciliation_required(
                instruction=instruction,
                changed_at=evaluated_at,
                message=(
                    "LIVE SELL accepted without "
                    "broker reference"
                ),
                exit_intent_id=(
                    intent.intent_id.value
                ),
            )

        # ----------------------------------------------------
        # Immediate authoritative broker refresh.
        # ----------------------------------------------------

        try:
            snapshot = (
                self._durable_exit_provider
                .get_exit_status(
                    reference
                )
            )

        except Exception as exc:
            return self._mark_reconciliation_required(
                instruction=instruction,
                changed_at=evaluated_at,
                message=(
                    "LIVE SELL status refresh failed: "
                    f"{exc}"
                ),
                exit_intent_id=(
                    intent.intent_id.value
                ),
                broker_order_id=(
                    reference.order_id
                ),
            )

        managed = self._checkpoint_snapshot(
            intent=intent,
            snapshot=snapshot,
            maintain_active_exit=True,
        )

        if (
            snapshot.status
            is BrokerOrderStatus.FILLED
        ):
            return (
                TradingDayForceExitInstructionResult(
                    instruction=instruction,
                    status=(
                        TradingDayForceExitRuntimeStatus
                        .POSITION_CLOSED
                    ),
                    position=managed,
                    exit_intent_id=(
                        intent.intent_id.value
                    ),
                    broker_order_id=(
                        reference.order_id
                    ),
                )
            )

        if (
            snapshot.status
            in self._ACTIVE_BROKER_STATUSES
        ):
            return (
                TradingDayForceExitInstructionResult(
                    instruction=instruction,
                    status=(
                        TradingDayForceExitRuntimeStatus
                        .REPLACEMENT_ACTIVE
                        if replacement
                        else
                        TradingDayForceExitRuntimeStatus
                        .LIVE_EXIT_ACTIVE
                    ),
                    position=managed,
                    exit_intent_id=(
                        intent.intent_id.value
                    ),
                    broker_order_id=(
                        reference.order_id
                    ),
                )
            )

        if (
            snapshot.status
            is BrokerOrderStatus.CANCELLED
        ):
            cancelled_changed_at = max(
                evaluated_at,
                snapshot.updated_at,
            )

            self._release_cancelled_guard(
                position_id=(
                    instruction.position_id.value
                ),
                changed_at=(
                    cancelled_changed_at
                ),
            )

            restored = self._restore_after_cancel(
                position_id=(
                    instruction.position_id
                ),
                changed_at=(
                    cancelled_changed_at
                ),
            )

            return (
                TradingDayForceExitInstructionResult(
                    instruction=instruction,
                    status=(
                        TradingDayForceExitRuntimeStatus
                        .RETRY_REQUIRED
                    ),
                    position=restored,
                    exit_intent_id=(
                        intent.intent_id.value
                    ),
                    broker_order_id=(
                        reference.order_id
                    ),
                    message=(
                        f"{operation_label} SELL is cancelled; "
                        "retry remains required"
                    ),
                )
            )

        return self._mark_reconciliation_required(
            instruction=instruction,
            changed_at=evaluated_at,
            message=(
                f"{operation_label} SELL requires broker "
                f"reconciliation: {snapshot.status.value}"
            ),
            exit_intent_id=(
                intent.intent_id.value
            ),
            broker_order_id=(
                reference.order_id
            ),
        )

    # ========================================================
    # RECONCILE_EXISTING_EXIT
    # ========================================================

    def _reconcile_existing_exit(
        self,
        *,
        instruction: ForceExitInstruction,
        evaluated_at: datetime,
    ) -> TradingDayForceExitInstructionResult:
        position = (
            self._position_registry.require(
                instruction.position_id
            )
        )

        # DRY_RUN creates no durable broker SELL context.
        if (
            self._execution_mode
            is ExecutionMode.DRY_RUN
        ):
            return (
                TradingDayForceExitInstructionResult(
                    instruction=instruction,
                    status=(
                        TradingDayForceExitRuntimeStatus
                        .DRY_RUN_PENDING
                    ),
                    position=position,
                    message=(
                        "DRY_RUN exit remains simulated; "
                        "no broker reconciliation performed"
                    ),
                )
            )

        durable_sell = (
            self._find_active_durable_sell(
                position_id=(
                    instruction.position_id.value
                )
            )
        )

        if durable_sell is None:
            return self._mark_reconciliation_required(
                instruction=instruction,
                changed_at=evaluated_at,
                message=(
                    "no unique durable unresolved SELL "
                    "exists for position"
                ),
            )

        if (
            durable_sell.broker_name is None
            or durable_sell.broker_order_id is None
        ):
            return self._mark_reconciliation_required(
                instruction=instruction,
                changed_at=evaluated_at,
                message=(
                    "durable SELL has no broker reference"
                ),
                exit_intent_id=(
                    durable_sell.order_intent_id
                ),
            )

        try:
            active_intent = (
                self._reconstruct_exit_intent(
                    durable_sell=durable_sell,
                    position=position,
                )
            )

            broker_reference = (
                BrokerOrderReference(
                    broker_name=(
                        durable_sell.broker_name
                    ),
                    order_id=(
                        durable_sell.broker_order_id
                    ),
                )
            )

        except Exception as exc:
            return self._mark_reconciliation_required(
                instruction=instruction,
                changed_at=evaluated_at,
                message=(
                    "durable SELL reconstruction failed: "
                    f"{exc}"
                ),
                exit_intent_id=(
                    durable_sell.order_intent_id
                ),
                broker_order_id=(
                    durable_sell.broker_order_id
                ),
            )

        reconciliation = (
            self._exit_reconciliation
            .reconcile_for_force_exit(
                position=position.position,
                active_exit_intent=(
                    active_intent
                ),
                broker_reference=(
                    broker_reference
                ),
                requested_at=evaluated_at,
            )
        )

        managed = (
            self._position_registry.require(
                instruction.position_id
            )
        )

        final_snapshot = (
            reconciliation.final_snapshot
        )

        reconciliation_changed_at = (
            evaluated_at
            if final_snapshot is None
            else max(
                evaluated_at,
                final_snapshot.updated_at,
            )
        )

        # ----------------------------------------------------
        # Every authoritative final broker snapshot crosses the
        # durable fill -> M07 -> PositionRecord boundary before
        # any replacement order is submitted.
        # ----------------------------------------------------

        if final_snapshot is not None:
            managed = self._checkpoint_snapshot(
                intent=active_intent,
                snapshot=final_snapshot,
                maintain_active_exit=False,
            )

        if (
            reconciliation.decision
            is ExitReconciliationDecision
            .POSITION_ALREADY_CLOSED
        ):
            if (
                managed.open_quantity != 0
                or managed.state
                is not ManagedPositionState.CLOSED
            ):
                return self._mark_reconciliation_required(
                    instruction=instruction,
                    changed_at=(
                        reconciliation_changed_at
                    ),
                    message=(
                        "broker reports completed SELL but "
                        "M07 position is not CLOSED"
                    ),
                    exit_intent_id=(
                        active_intent.intent_id.value
                    ),
                    broker_order_id=(
                        broker_reference.order_id
                    ),
                )

            return (
                TradingDayForceExitInstructionResult(
                    instruction=instruction,
                    status=(
                        TradingDayForceExitRuntimeStatus
                        .POSITION_CLOSED
                    ),
                    position=managed,
                    exit_intent_id=(
                        active_intent.intent_id.value
                    ),
                    broker_order_id=(
                        broker_reference.order_id
                    ),
                )
            )

        if (
            reconciliation.decision
            is ExitReconciliationDecision
            .FORCE_EXIT_READY
        ):
            plan = reconciliation.force_exit_plan

            if plan is None:
                raise RuntimeError(
                    "FORCE_EXIT_READY requires plan"
                )

            if final_snapshot is None:
                raise RuntimeError(
                    "FORCE_EXIT_READY requires final "
                    "broker snapshot"
                )

            if (
                final_snapshot.status
                is not BrokerOrderStatus.CANCELLED
            ):
                raise RuntimeError(
                    "force-exit replacement requires "
                    "confirmed CANCELLED old SELL"
                )

            if managed.open_quantity <= 0:
                return (
                    TradingDayForceExitInstructionResult(
                        instruction=instruction,
                        status=(
                            TradingDayForceExitRuntimeStatus
                            .POSITION_CLOSED
                        ),
                        position=managed,
                        exit_intent_id=(
                            active_intent.intent_id.value
                        ),
                        broker_order_id=(
                            broker_reference.order_id
                        ),
                    )
                )

            restored = self._restore_after_cancel(
                position_id=(
                    instruction.position_id
                ),
                changed_at=(
                    reconciliation_changed_at
                ),
            )

            if (
                reconciliation.remaining_quantity
                != restored.open_quantity
                or plan.quantity
                != restored.open_quantity
            ):
                return self._mark_reconciliation_required(
                    instruction=instruction,
                    changed_at=(
                        reconciliation_changed_at
                    ),
                    message=(
                        "reconciliation replacement quantity "
                        "does not equal durable open quantity"
                    ),
                    exit_intent_id=(
                        active_intent.intent_id.value
                    ),
                    broker_order_id=(
                        broker_reference.order_id
                    ),
                )

            # Old SELL is now terminal and PositionRecord is
            # durable. Only now may M07/M06 submit replacement.
            return self._submit_force_exit(
                instruction=instruction,
                quantity=(
                    restored.open_quantity
                ),
                evaluated_at=(
                    reconciliation_changed_at
                ),
                replacement=True,
            )

        # ----------------------------------------------------
        # Cancellation/status uncertainty.
        #
        # Keep EXIT_ONLY and persist conservative M07 state.
        # ----------------------------------------------------

        return self._mark_reconciliation_required(
            instruction=instruction,
            changed_at=(
                reconciliation_changed_at
            ),
            message=(
                reconciliation.message
                or (
                    "existing SELL reconciliation "
                    f"requires attention: "
                    f"{reconciliation.decision.value}"
                )
            ),
            exit_intent_id=(
                active_intent.intent_id.value
            ),
            broker_order_id=(
                broker_reference.order_id
            ),
        )

    # ========================================================
    # Durable snapshot application
    # ========================================================

    def _checkpoint_snapshot(
        self,
        *,
        intent: ExitOrderIntent,
        snapshot,
        maintain_active_exit: bool,
    ) -> ManagedPosition:
        delta = (
            self._exit_persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=snapshot,
            )
        )

        managed = (
            self._position_registry.require(
                intent.position_id
            )
        )

        if delta.has_fill:
            if delta.price is None:
                raise RuntimeError(
                    "positive durable SELL fill "
                    "requires price"
                )

            managed = (
                self._position_lifecycle_manager
                .apply_exit_fill(
                    position_id=(
                        intent.position_id
                    ),
                    fill_quantity=(
                        delta.quantity
                    ),
                    fill_price=delta.price,
                    filled_at=delta.filled_at,
                )
            )

        # A partially filled but still-live broker SELL remains
        # EXIT_PENDING so repeated 15:15 cycles reconcile it
        # instead of submitting another SELL.
        if (
            maintain_active_exit
            and snapshot.status
            in self._ACTIVE_BROKER_STATUSES
            and managed.open_quantity > 0
            and managed.state
            is ManagedPositionState.PARTIALLY_EXITED
        ):
            managed = (
                self._position_lifecycle_manager
                .mark_exit_pending(
                    position_id=(
                        intent.position_id
                    ),
                    trigger=(
                        RiskTriggerType.FORCE_EXIT
                    ),
                    changed_at=(
                        snapshot.updated_at
                    ),
                )
            )

        if (
            snapshot.status
            is BrokerOrderStatus.UNKNOWN
            and managed.open_quantity > 0
        ):
            managed = (
                self._position_lifecycle_manager
                .mark_reconciliation_required(
                    position_id=(
                        intent.position_id
                    ),
                    changed_at=(
                        snapshot.updated_at
                    ),
                )
            )

        # PositionRecord is persisted before terminal SELL
        # OrderRecord inside this method.
        self._exit_persistence\
            .persist_managed_position_after_snapshot(
                intent=intent,
                snapshot=snapshot,
                managed_position=managed,
            )

        return managed

    # ========================================================
    # Durable SELL reconstruction
    # ========================================================

    def _find_active_durable_sell(
        self,
        *,
        position_id: str,
    ) -> OrderRecord | None:
        matches = tuple(
            record
            for record
            in self._order_repository
            .list_open_orders_for_position(
                position_id
            )
            if (
                record.side == "SELL"
                and record.position_id
                == position_id
            )
        )

        if len(matches) != 1:
            return None

        return matches[0]

    @staticmethod
    def _reconstruct_exit_intent(
        *,
        durable_sell: OrderRecord,
        position: ManagedPosition,
    ) -> ExitOrderIntent:
        return ExitOrderIntent(
            intent_id=ExitOrderIntentId(
                durable_sell.order_intent_id
            ),
            position_id=(
                position.position_id
            ),
            security_id=(
                durable_sell.security_id
            ),
            symbol=(
                durable_sell.symbol
            ),
            option_type=(
                position.position.option_type
            ),
            transaction_type=(
                ExitTransactionType.SELL
            ),
            order_type=ExitOrderType(
                durable_sell.order_type
            ),
            quantity=(
                durable_sell.quantity
            ),
            price=(
                durable_sell.limit_price
            ),
            reason=ExitReason(
                durable_sell.reason
            ),
            created_at=(
                durable_sell.created_at
            ),
        )

    # ========================================================
    # Lifecycle recovery helpers
    # ========================================================

    def _restore_after_cancel(
        self,
        *,
        position_id,
        changed_at: datetime,
    ) -> ManagedPosition:
        position = (
            self._position_registry.require(
                position_id
            )
        )

        if position.open_quantity <= 0:
            return position

        if (
            position.state
            in {
                ManagedPositionState.EXIT_PENDING,
                ManagedPositionState
                .RECONCILIATION_REQUIRED,
            }
        ):
            position = (
                self._position_lifecycle_manager
                .restore_after_reconciliation(
                    position_id=position_id,
                    changed_at=changed_at,
                )
            )

        elif (
            position.state
            not in {
                ManagedPositionState.OPEN,
                ManagedPositionState
                .PARTIALLY_EXITED,
            }
        ):
            raise RuntimeError(
                "cancelled SELL cannot restore "
                f"position from {position.state.value}"
            )

        self._exit_persistence\
            .persist_managed_position_state(
                managed_position=position
            )

        return position

    def _release_cancelled_guard(
        self,
        *,
        position_id: str,
        changed_at: datetime,
    ) -> None:
        key = IdempotencyKey(
            value=(
                "EXIT_POSITION:"
                f"{position_id}"
            )
        )

        record = (
            self._duplicate_guard.get(
                key
            )
        )

        if (
            record is not None
            and record.state
            is IdempotencyState.SUBMITTED
        ):
            self._duplicate_guard\
                .release_after_reconciliation(
                    key=key,
                    changed_at=changed_at,
                )

    def _mark_reconciliation_required(
        self,
        *,
        instruction: ForceExitInstruction,
        changed_at: datetime,
        message: str,
        exit_intent_id: str | None = None,
        broker_order_id: str | None = None,
    ) -> TradingDayForceExitInstructionResult:
        position = (
            self._position_registry.require(
                instruction.position_id
            )
        )

        if (
            position.open_quantity > 0
            and position.state
            is not ManagedPositionState.CLOSED
        ):
            position = (
                self._position_lifecycle_manager
                .mark_reconciliation_required(
                    position_id=(
                        instruction.position_id
                    ),
                    changed_at=changed_at,
                )
            )

            self._exit_persistence\
                .persist_managed_position_state(
                    managed_position=position
                )

        return (
            TradingDayForceExitInstructionResult(
                instruction=instruction,
                status=(
                    TradingDayForceExitRuntimeStatus
                    .RECONCILIATION_REQUIRED
                ),
                position=position,
                exit_intent_id=(
                    exit_intent_id
                ),
                broker_order_id=(
                    broker_order_id
                ),
                message=message,
            )
        )

    def _fail_closed(
        self,
        *,
        instruction: ForceExitInstruction,
        changed_at: datetime,
        message: str,
    ) -> TradingDayForceExitInstructionResult:
        position = (
            self._position_registry.require(
                instruction.position_id
            )
        )

        if (
            instruction.action
            is not ForceExitAction.NONE
            and position.open_quantity > 0
            and position.state
            is not ManagedPositionState.CLOSED
        ):
            try:
                position = (
                    self._position_lifecycle_manager
                    .mark_reconciliation_required(
                        position_id=(
                            instruction.position_id
                        ),
                        changed_at=changed_at,
                    )
                )

                self._exit_persistence\
                    .persist_managed_position_state(
                        managed_position=position
                    )

            except Exception as persistence_exc:
                message = (
                    f"{message}; failed to persist "
                    "fail-closed position state: "
                    f"{persistence_exc}"
                )

        return (
            TradingDayForceExitInstructionResult(
                instruction=instruction,
                status=(
                    TradingDayForceExitRuntimeStatus
                    .FAILED_CLOSED
                ),
                position=position,
                message=message,
            )
        )


__all__ += [
    "TradingDayForceExitInstructionResult",
    "TradingDayForceExitRuntimeCoordinator",
    "TradingDayForceExitRuntimeResult",
    "TradingDayForceExitRuntimeStatus",
]
