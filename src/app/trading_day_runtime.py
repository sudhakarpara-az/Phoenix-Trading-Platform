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

from src.account.account_execution_gate import (
    AccountEntryBlockedError,
    AccountExecutionSafetyGate,
    AccountGatedEntryResult,
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

from src.option_selection.option_types import (
    OptionType,
    SelectedOption,
)
from src.services.scheduler import (
    TradingDayEntryGateCoordinator,
    TradingDayEntryGateDecision,
    TradingDayLevelPreparationResult,
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

            # Only after broker fill + M07 risk initialization
            # are fully established does M04 become ACTIVE.
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
