"""
Phoenix M07-T21 Failure & Edge-Case Tests.

Hardens the Position & Risk Management Engine against:

    - invalid M06 -> M07 initialization
    - duplicate M07 registration
    - invalid/stale market prices
    - missing target/stop configuration
    - stale exit decisions
    - duplicate exit lifecycle transitions
    - over-fills / invalid broker fills
    - P&L ledger inconsistencies
    - reconciliation safety
    - premature re-entry release
    - force-exit duplicate SELL races

No real broker orders are placed.
"""

from datetime import (
    date,
    datetime,
    timedelta,
)

import math
import pytest

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
    OrderIntentId,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderSnapshot,
)
from src.execution.exit_execution_service import (
    ExitExecutionService,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
)
from src.execution.position_exit_types import (
    FilledPosition,
    FilledPositionId,
)
from src.execution.target_booking_policy import (
    TargetBookingPolicy,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.risk.filled_position_risk_initializer import (
    FilledPositionRiskInitializer,
)
from src.risk.force_exit_coordinator import (
    ForceExitAction,
    ForceExitCoordinator,
)
from src.risk.m06_exit_integration_service import (
    M07ExitIntegrationStatus,
    M07ToM06ExitIntegrationService,
)
from src.risk.option_position_price_monitor import (
    OptionPositionPriceMonitor,
    OptionPriceTick,
    PriceUpdateStatus,
)
from src.risk.position_exit_decision_engine import (
    PositionExitDecision,
    PositionExitDecisionEngine,
    PositionExitDecisionStatus,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_pnl_tracker import (
    PositionPnLTracker,
)
from src.risk.position_registry import (
    DuplicatePositionError,
    PositionRegistry,
)
from src.risk.reentry_risk_synchronizer import (
    ReentryRiskSynchronizer,
    ReentrySyncStatus,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    RiskTriggerType,
    StopLossDefinition,
    TargetDefinition,
)
from src.risk.stop_loss_policy import (
    StopLossConfig,
    StopLossPolicy,
)
from src.risk.stop_loss_trigger_monitor import (
    StopLossTriggerMonitor,
    StopLossTriggerStatus,
)
from src.risk.target_trigger_monitor import (
    TargetTriggerMonitor,
    TargetTriggerStatus,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


EXPIRY = date(
    2026,
    8,
    11,
)

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)

LATER = (
    NOW
    + timedelta(seconds=1)
)

FORCE_TIME = datetime(
    2026,
    8,
    7,
    15,
    15,
)


class FakeReentryPort:
    def __init__(self) -> None:
        self.open_calls = []
        self.closed_calls = []

    def mark_position_open(
        self,
        *,
        instrument_security_id,
        level,
        position_id,
        changed_at,
    ) -> None:
        self.open_calls.append(
            (
                level,
                position_id,
                changed_at,
                instrument_security_id,
            )
        )

    def mark_position_closed(
        self,
        *,
        instrument_security_id,
        level,
        position_id,
        changed_at,
    ) -> None:
        self.closed_calls.append(
            (
                level,
                position_id,
                changed_at,
                instrument_security_id,
            )
        )


class SuccessfulExitProvider(
    ExitExecutionProvider
):
    def __init__(self) -> None:
        self.submit_count = 0

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent,
    ) -> ExitExecutionResult:
        self.submit_count += 1

        return ExitExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=(
                BrokerOrderReference(
                    broker_name="FAKE",
                    order_id=(
                        f"EXIT-{self.submit_count}"
                    ),
                )
            ),
            submitted_at=NOW,
        )

    def cancel_exit(
        self,
        broker_reference,
    ) -> ExitCancellationResult:
        raise NotImplementedError

    def get_exit_status(
        self,
        broker_reference,
    ) -> ExitOrderSnapshot:
        raise NotImplementedError


class FailingExitProvider(
    ExitExecutionProvider
):
    def __init__(self) -> None:
        self.submit_count = 0

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent,
    ) -> ExitExecutionResult:
        self.submit_count += 1

        raise RuntimeError(
            "simulated broker timeout"
        )

    def cancel_exit(
        self,
        broker_reference,
    ) -> ExitCancellationResult:
        raise NotImplementedError

    def get_exit_status(
        self,
        broker_reference,
    ) -> ExitOrderSnapshot:
        raise NotImplementedError


def make_option(
    *,
    security_id: str = "41009",
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-24450-CE"
                ),
                security_id=security_id,
                option_type=OptionType.CALL,
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=100,
                bid=99.95,
                ask=100.05,
                volume=1000,
                open_interest=50000,
                received_at=NOW,
            ),
            greeks=OptionGreeks(
                delta=0.64,
                calculated_at=NOW,
            ),
        ),
        selected_at=NOW,
        selection_delta_target=0.64,
    )


def make_filled_position(
    *,
    position_id: str = "POS-M07-T21",
    quantity: int = 65,
    entry_price: float = 100,
    level: EntryLevel = EntryLevel.K5,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            position_id
        ),
        signal_id=SignalId(
            f"SIG-{position_id}"
        ),
        entry_intent_id=OrderIntentId(
            f"ORD-{position_id}"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id=(
                    f"ENTRY-{position_id}"
                ),
            )
        ),
        selected_option=make_option(),
        level=level,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )


def make_managed_position(
    *,
    position_id: str = "POS-M07-T21",
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
    entry_price: float = 100,
    with_stop: bool = True,
    with_target: bool = True,
) -> ManagedPosition:
    filled = make_filled_position(
        position_id=position_id,
        quantity=quantity,
        entry_price=entry_price,
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            f"RISK-{position_id}"
        ),
        position=filled,
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
        stop_loss=(
            StopLossDefinition(
                stop_price=85,
                risk_points=15,
            )
            if with_stop
            else None
        ),
        target=(
            TargetDefinition(
                executable_price=126,
                mapped_target_price=129,
                booking_zone_start=126,
                booking_zone_end=129,
            )
            if with_target
            else None
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def make_registry(
    position: ManagedPosition | None = None,
) -> PositionRegistry:
    registry = PositionRegistry()

    if position is not None:
        registry.register(
            position
        )

    return registry


def make_exit_integration(
    *,
    registry: PositionRegistry,
    provider: ExitExecutionProvider,
):
    lifecycle = PositionLifecycleManager(
        registry=registry
    )

    exit_service = ExitExecutionService(
        provider=provider,
        duplicate_guard=DuplicateOrderGuard(),
        allow_live_exit_orders=True,
    )

    integration = (
        M07ToM06ExitIntegrationService(
            registry=registry,
            lifecycle_manager=lifecycle,
            exit_plan_builder=(
                ExitPlanBuilder(
                    TargetBookingPolicy()
                )
            ),
            exit_execution_service=(
                exit_service
            ),
        )
    )

    return lifecycle, integration


# ============================================================
# M06 -> M07 initialization failures
# ============================================================


def test_initializer_rejects_time_before_fill() -> None:
    registry = PositionRegistry()

    initializer = (
        FilledPositionRiskInitializer(
            registry=registry,
            stop_loss_policy=(
                StopLossPolicy()
            ),
        )
    )

    filled = make_filled_position()

    with pytest.raises(
        ValueError,
        match=(
            "initialized_at cannot be before "
            "position filled_at"
        ),
    ):
        initializer.initialize(
            position=filled,
            initialized_at=(
                NOW
                - timedelta(seconds=1)
            ),
        )

    assert registry.count() == 0


def test_initializer_rejects_duplicate_position() -> None:
    registry = PositionRegistry()

    initializer = (
        FilledPositionRiskInitializer(
            registry=registry,
            stop_loss_policy=(
                StopLossPolicy()
            ),
        )
    )

    filled = make_filled_position()

    initializer.initialize(
        position=filled,
        initialized_at=NOW,
    )

    with pytest.raises(
        DuplicatePositionError
    ):
        initializer.initialize(
            position=filled,
            initialized_at=LATER,
        )

    assert registry.count() == 1


def test_initializer_rejects_entry_too_small_for_stop() -> None:
    registry = PositionRegistry()

    initializer = (
        FilledPositionRiskInitializer(
            registry=registry,
            stop_loss_policy=StopLossPolicy(
                StopLossConfig(
                    risk_points=15
                )
            ),
        )
    )

    filled = make_filled_position(
        entry_price=10
    )

    with pytest.raises(
        ValueError,
        match=(
            "configured risk_points produce "
            "a non-positive stop price"
        ),
    ):
        initializer.initialize(
            position=filled,
            initialized_at=NOW,
        )

    assert registry.count() == 0


# ============================================================
# Price monitor failures
# ============================================================


def test_untracked_option_tick_is_ignored() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="99999",
            ltp=100,
            received_at=NOW,
        )
    )

    assert (
        result.status
        is PriceUpdateStatus
        .UNTRACKED_SECURITY
    )

    assert result.accepted is False


def test_closed_position_tick_is_rejected() -> None:
    position = make_managed_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=100,
            received_at=NOW,
        )
    )

    assert (
        result.status
        is PriceUpdateStatus
        .NO_OPEN_POSITION
    )


def test_out_of_order_price_does_not_replace_latest() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=110,
            received_at=LATER,
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=80,
            received_at=NOW,
        )
    )

    assert (
        result.status
        is PriceUpdateStatus.STALE_TICK
    )

    latest = monitor.get_by_security_id(
        "41009"
    )

    assert latest is not None
    assert latest.ltp == 110


def test_invalid_zero_price_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "ltp must be greater than zero"
        ),
    ):
        OptionPriceTick(
            security_id="41009",
            ltp=0,
            received_at=NOW,
        )


def test_nan_price_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="ltp must be finite",
    ):
        OptionPriceTick(
            security_id="41009",
            ltp=math.nan,
            received_at=NOW,
        )


# ============================================================
# Target / stop monitor failure handling
# ============================================================


def test_target_monitor_fails_closed_on_stale_price() -> None:
    position = make_managed_position()

    registry = make_registry(
        position
    )

    prices = OptionPositionPriceMonitor(
        registry=registry
    )

    monitor = TargetTriggerMonitor(
        price_monitor=prices,
        max_price_age=timedelta(
            seconds=5
        ),
    )

    prices.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=130,
            received_at=NOW,
        )
    )

    result = monitor.evaluate(
        position=position,
        evaluated_at=(
            NOW
            + timedelta(seconds=10)
        ),
    )

    assert (
        result.status
        is TargetTriggerStatus.STALE_PRICE
    )

    assert result.triggered is False


def test_stop_monitor_fails_closed_on_stale_price() -> None:
    position = make_managed_position()

    registry = make_registry(
        position
    )

    prices = OptionPositionPriceMonitor(
        registry=registry
    )

    monitor = StopLossTriggerMonitor(
        price_monitor=prices,
        max_price_age=timedelta(
            seconds=5
        ),
    )

    prices.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=80,
            received_at=NOW,
        )
    )

    result = monitor.evaluate(
        position=position,
        evaluated_at=(
            NOW
            + timedelta(seconds=10)
        ),
    )

    assert (
        result.status
        is StopLossTriggerStatus.STALE_PRICE
    )

    assert result.triggered is False


def test_target_monitor_handles_missing_target() -> None:
    position = make_managed_position(
        with_target=False
    )

    registry = make_registry(
        position
    )

    prices = OptionPositionPriceMonitor(
        registry=registry
    )

    monitor = TargetTriggerMonitor(
        price_monitor=prices
    )

    result = monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is TargetTriggerStatus.NO_TARGET
    )


def test_stop_monitor_handles_missing_stop() -> None:
    position = make_managed_position(
        with_stop=False
    )

    registry = make_registry(
        position
    )

    prices = OptionPositionPriceMonitor(
        registry=registry
    )

    monitor = StopLossTriggerMonitor(
        price_monitor=prices
    )

    result = monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus
        .NO_STOP_LOSS
    )


# ============================================================
# Exit decision failures
# ============================================================


def test_closed_position_never_generates_exit() -> None:
    engine = PositionExitDecisionEngine()

    position = make_managed_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .POSITION_CLOSED
    )

    assert result.exit_required is False
    assert result.quantity == 0


def test_exit_pending_position_blocks_new_force_exit() -> None:
    engine = PositionExitDecisionEngine()

    position = make_managed_position(
        state=ManagedPositionState.EXIT_PENDING
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .EXIT_ALREADY_PENDING
    )

    assert result.exit_required is False


def test_reconciliation_position_blocks_new_exit() -> None:
    engine = PositionExitDecisionEngine()

    position = make_managed_position(
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        )
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .RECONCILIATION_REQUIRED
    )

    assert result.exit_required is False


# ============================================================
# Lifecycle failures
# ============================================================


def test_lifecycle_rejects_second_exit_pending_transition() -> None:
    position = make_managed_position()

    registry = make_registry(
        position
    )

    lifecycle = PositionLifecycleManager(
        registry=registry
    )

    lifecycle.mark_exit_pending(
        position_id=position.position_id,
        trigger=RiskTriggerType.TARGET,
        changed_at=NOW,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "position already has an exit pending"
        ),
    ):
        lifecycle.mark_exit_pending(
            position_id=position.position_id,
            trigger=RiskTriggerType.STOP_LOSS,
            changed_at=LATER,
        )


def test_lifecycle_rejects_overfill() -> None:
    position = make_managed_position()

    registry = make_registry(
        position
    )

    lifecycle = PositionLifecycleManager(
        registry=registry
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit fill quantity cannot exceed "
            "open position quantity"
        ),
    ):
        lifecycle.apply_exit_fill(
            position_id=position.position_id,
            fill_quantity=66,
            fill_price=120,
            filled_at=NOW,
        )


def test_lifecycle_rejects_fill_after_close() -> None:
    position = make_managed_position()

    registry = make_registry(
        position
    )

    lifecycle = PositionLifecycleManager(
        registry=registry
    )

    lifecycle.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=65,
        fill_price=120,
        filled_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "cannot apply exit fill to closed position"
        ),
    ):
        lifecycle.apply_exit_fill(
            position_id=position.position_id,
            fill_quantity=1,
            fill_price=120,
            filled_at=LATER,
        )


def test_reconciliation_state_blocks_exit_pending() -> None:
    position = make_managed_position(
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        )
    )

    registry = make_registry(
        position
    )

    lifecycle = PositionLifecycleManager(
        registry=registry
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "requires reconciliation before "
            "new exit can be marked pending"
        ),
    ):
        lifecycle.mark_exit_pending(
            position_id=position.position_id,
            trigger=RiskTriggerType.FORCE_EXIT,
            changed_at=NOW,
        )


# ============================================================
# P&L tracker failures
# ============================================================


def test_pnl_tracker_rejects_duplicate_registration() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "position already registered for "
            "P&L tracking"
        ),
    ):
        tracker.register(
            position=position,
            registered_at=LATER,
        )


def test_pnl_tracker_rejects_overfill() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit fill quantity cannot exceed "
            "tracked open quantity"
        ),
    ):
        tracker.record_exit_fill(
            position_id=position.position_id,
            quantity=66,
            price=120,
            filled_at=LATER,
        )


def test_pnl_tracker_rejects_stale_mark() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    tracker.mark_to_market(
        position_id=position.position_id,
        ltp=110,
        marked_at=LATER,
    )

    with pytest.raises(
        ValueError,
        match=(
            "mark timestamp must be newer than "
            "latest mark"
        ),
    ):
        tracker.mark_to_market(
            position_id=position.position_id,
            ltp=90,
            marked_at=NOW,
        )


def test_pnl_tracker_closed_position_has_zero_unrealized() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    tracker.record_exit_fill(
        position_id=position.position_id,
        quantity=65,
        price=120,
        filled_at=LATER,
    )

    state = tracker.mark_to_market(
        position_id=position.position_id,
        ltp=200,
        marked_at=(
            LATER
            + timedelta(seconds=1)
        ),
    )

    assert state.open_quantity == 0
    assert state.unrealized_pnl == 0


# ============================================================
# M07 -> M06 integration failures
# ============================================================


def test_stale_exit_quantity_is_rejected_before_sell() -> None:
    position = make_managed_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    registry = make_registry(
        position
    )

    provider = SuccessfulExitProvider()

    _, integration = make_exit_integration(
        registry=registry,
        provider=provider,
    )

    stale_decision = PositionExitDecision(
        status=(
            PositionExitDecisionStatus
            .EXIT_REQUIRED
        ),
        position_id=position.position_id,
        trigger=RiskTriggerType.STOP_LOSS,
        quantity=65,
        decided_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit decision quantity must equal "
            "managed position open quantity"
        ),
    ):
        integration.execute_decision(
            decision=stale_decision,
            execution_mode=ExecutionMode.LIVE,
            requested_at=NOW,
        )

    assert provider.submit_count == 0


def test_target_exit_without_target_is_rejected_before_sell() -> None:
    position = make_managed_position(
        with_target=False
    )

    registry = make_registry(
        position
    )

    provider = SuccessfulExitProvider()

    _, integration = make_exit_integration(
        registry=registry,
        provider=provider,
    )

    decision = PositionExitDecision(
        status=(
            PositionExitDecisionStatus
            .EXIT_REQUIRED
        ),
        position_id=position.position_id,
        trigger=RiskTriggerType.TARGET,
        quantity=65,
        decided_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "TARGET exit requires mapped "
            "option target"
        ),
    ):
        integration.execute_decision(
            decision=decision,
            execution_mode=ExecutionMode.LIVE,
            requested_at=NOW,
        )

    assert provider.submit_count == 0

    assert (
        registry.require(
            position.position_id
        ).state
        is ManagedPositionState.OPEN
    )


def test_stop_exit_without_stop_is_rejected_before_sell() -> None:
    position = make_managed_position(
        with_stop=False
    )

    registry = make_registry(
        position
    )

    provider = SuccessfulExitProvider()

    _, integration = make_exit_integration(
        registry=registry,
        provider=provider,
    )

    decision = PositionExitDecision(
        status=(
            PositionExitDecisionStatus
            .EXIT_REQUIRED
        ),
        position_id=position.position_id,
        trigger=RiskTriggerType.STOP_LOSS,
        quantity=65,
        decided_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "STOP_LOSS exit requires configured "
            "stop loss"
        ),
    ):
        integration.execute_decision(
            decision=decision,
            execution_mode=ExecutionMode.LIVE,
            requested_at=NOW,
        )

    assert provider.submit_count == 0


def test_broker_failure_requires_reconciliation() -> None:
    position = make_managed_position()

    registry = make_registry(
        position
    )

    provider = FailingExitProvider()

    _, integration = make_exit_integration(
        registry=registry,
        provider=provider,
    )

    decision = PositionExitDecision(
        status=(
            PositionExitDecisionStatus
            .EXIT_REQUIRED
        ),
        position_id=position.position_id,
        trigger=RiskTriggerType.STOP_LOSS,
        quantity=65,
        decided_at=NOW,
    )

    result = integration.execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert (
        result.status
        is M07ExitIntegrationStatus
        .RECONCILIATION_REQUIRED
    )

    assert (
        registry.require(
            position.position_id
        ).state
        is ManagedPositionState
        .RECONCILIATION_REQUIRED
    )


def test_broker_failure_does_not_restore_open_state() -> None:
    position = make_managed_position()

    registry = make_registry(
        position
    )

    provider = FailingExitProvider()

    _, integration = make_exit_integration(
        registry=registry,
        provider=provider,
    )

    decision = PositionExitDecision(
        status=(
            PositionExitDecisionStatus
            .EXIT_REQUIRED
        ),
        position_id=position.position_id,
        trigger=RiskTriggerType.FORCE_EXIT,
        quantity=65,
        decided_at=FORCE_TIME,
    )

    integration.execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=FORCE_TIME,
    )

    stored = registry.require(
        position.position_id
    )

    assert (
        stored.state
        is not ManagedPositionState.OPEN
    )


# ============================================================
# Force exit failures / duplicate protection
# ============================================================


def test_1515_pending_exit_routes_to_reconciliation() -> None:
    position = make_managed_position(
        state=ManagedPositionState.EXIT_PENDING
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert result.force_exit_required is False


def test_1515_reconciliation_state_never_requests_new_sell() -> None:
    position = make_managed_position(
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        )
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert result.force_exit_required is False


def test_1515_closed_position_has_no_action() -> None:
    position = make_managed_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is ForceExitAction.NONE
    )

    assert result.quantity == 0


# ============================================================
# Re-entry safety failures
# ============================================================


def test_exit_pending_does_not_release_reentry() -> None:
    position = make_managed_position(
        state=ManagedPositionState.EXIT_PENDING
    )

    registry = make_registry(
        position
    )

    port = FakeReentryPort()

    synchronizer = ReentryRiskSynchronizer(
        registry=registry,
        reentry_port=port,
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        result.status
        is ReentrySyncStatus.STILL_OPEN
    )

    assert result.reentry_released is False
    assert port.closed_calls == []


def test_partial_position_does_not_release_reentry() -> None:
    position = make_managed_position(
        open_quantity=1,
        closed_quantity=64,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    registry = make_registry(
        position
    )

    port = FakeReentryPort()

    synchronizer = ReentryRiskSynchronizer(
        registry=registry,
        reentry_port=port,
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert result.reentry_released is False
    assert port.closed_calls == []


def test_reconciliation_state_does_not_release_reentry() -> None:
    position = make_managed_position(
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        )
    )

    registry = make_registry(
        position
    )

    port = FakeReentryPort()

    synchronizer = ReentryRiskSynchronizer(
        registry=registry,
        reentry_port=port,
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert result.reentry_released is False
    assert port.closed_calls == []


def test_only_final_closed_state_releases_reentry() -> None:
    position = make_managed_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    registry = make_registry(
        position
    )

    port = FakeReentryPort()

    synchronizer = ReentryRiskSynchronizer(
        registry=registry,
        reentry_port=port,
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert result.reentry_released is True

    assert len(
        port.closed_calls
    ) == 1


def test_closed_reentry_sync_is_idempotent() -> None:
    position = make_managed_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    registry = make_registry(
        position
    )

    port = FakeReentryPort()

    synchronizer = ReentryRiskSynchronizer(
        registry=registry,
        reentry_port=port,
    )

    first = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    second = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=LATER,
    )

    assert first.reentry_released is True

    assert (
        second.status
        is ReentrySyncStatus.ALREADY_SYNCED
    )

    assert len(
        port.closed_calls
    ) == 1
