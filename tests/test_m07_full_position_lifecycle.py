"""
Phoenix M07-T20 Full Position Lifecycle Integration Tests.

Validates the complete lifecycle:

    M06 FilledPosition
        ->
    M07 initialization
        ->
    stop-loss initialization
        ->
    M04 re-entry synchronization
        ->
    option price monitoring
        ->
    P&L tracking
        ->
    target / stop evaluation
        ->
    exit decision
        ->
    M06 exit execution
        ->
    partial/final broker fills
        ->
    M07 lifecycle updates
        ->
    realized/unrealized P&L
        ->
    re-entry release only after actual closure

No real broker orders are placed.
"""

from datetime import (
    date,
    datetime,
    timedelta,
)

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
    ExitOrderType,
    ExitReason,
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
from src.risk.daily_risk_manager import (
    DailyRiskManager,
)
from src.risk.filled_position_risk_initializer import (
    FilledPositionRiskInitializer,
)
from src.risk.force_exit_coordinator import (
    ForceExitAction,
    ForceExitCoordinator,
)
from src.risk.m04_reentry_adapter import (
    M04ReentryAdapter,
)
from src.risk.m06_exit_integration_service import (
    M07ExitIntegrationStatus,
    M07ToM06ExitIntegrationService,
)
from src.risk.option_position_price_monitor import (
    OptionPositionPriceMonitor,
    OptionPriceTick,
)
from src.risk.position_exit_decision_engine import (
    PositionExitDecisionEngine,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_pnl_tracker import (
    PositionPnLTracker,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.reentry_risk_synchronizer import (
    ReentryRiskSynchronizer,
    ReentrySyncStatus,
)
from src.risk.risk_types import (
    ManagedPositionState,
    RiskTriggerType,
    TargetDefinition,
)
from src.risk.stop_loss_policy import (
    StopLossConfig,
    StopLossPolicy,
)
from src.risk.stop_loss_trigger_monitor import (
    StopLossTriggerMonitor,
)
from src.risk.target_trigger_monitor import (
    TargetTriggerMonitor,
)
from src.signals.reentry_state_manager import (
    ReentryStateManager,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


TRADING_DATE = date(
    2026,
    8,
    7,
)

EXPIRY = date(
    2026,
    8,
    11,
)

ENTRY_TIME = datetime(
    2026,
    8,
    7,
    10,
    0,
)

INIT_TIME = (
    ENTRY_TIME
    + timedelta(seconds=1)
)

PRICE_TIME = (
    ENTRY_TIME
    + timedelta(minutes=5)
)

TARGET_TIME = (
    ENTRY_TIME
    + timedelta(minutes=10)
)

PARTIAL_FILL_TIME = (
    TARGET_TIME
    + timedelta(seconds=1)
)

FINAL_FILL_TIME = (
    TARGET_TIME
    + timedelta(seconds=2)
)

FORCE_EXIT_TIME = datetime(
    2026,
    8,
    7,
    15,
    15,
)


class FakeExitProvider(
    ExitExecutionProvider
):
    """
    Fake M06 exit provider.

    Counts submitted SELL orders but never calls a real broker.
    """

    def __init__(self) -> None:
        self.submit_count = 0
        self.submitted_intents = []

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent,
    ) -> ExitExecutionResult:
        self.submit_count += 1

        self.submitted_intents.append(
            intent
        )

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
            submitted_at=TARGET_TIME,
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
    option_type: OptionType = OptionType.CALL,
) -> SelectedOption:
    side = (
        "CE"
        if option_type is OptionType.CALL
        else "PE"
    )

    delta = (
        0.64
        if option_type is OptionType.CALL
        else -0.64
    )

    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-"
                    f"24450-{side}"
                ),
                security_id=security_id,
                option_type=option_type,
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
                received_at=ENTRY_TIME,
            ),
            greeks=OptionGreeks(
                delta=delta,
                calculated_at=ENTRY_TIME,
            ),
        ),
        selected_at=ENTRY_TIME,
        selection_delta_target=0.64,
    )


def make_filled_position(
    *,
    position_id: str = "POS-M07-T20",
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
        filled_at=ENTRY_TIME,
    )


def build_runtime(
    *,
    filled_position: FilledPosition | None = None,
):
    """
    Build complete M07-T20 test runtime.
    """

    registry = PositionRegistry()

    stop_policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15,
            tick_size=0.05,
        )
    )

    initializer = (
        FilledPositionRiskInitializer(
            registry=registry,
            stop_loss_policy=stop_policy,
        )
    )

    filled = (
        filled_position
        or make_filled_position()
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    # --------------------------------------------------
    # Attach mapped option target.
    #
    # T09/T12 already test target mapping/building itself.
    # T20 starts with the valid option-domain target.
    # --------------------------------------------------

    managed = managed.__class__(
        risk_id=managed.risk_id,
        position=managed.position,
        open_quantity=managed.open_quantity,
        closed_quantity=managed.closed_quantity,
        realized_pnl=managed.realized_pnl,
        state=managed.state,
        stop_loss=managed.stop_loss,
        target=TargetDefinition(
            executable_price=126,
            mapped_target_price=129,
            booking_zone_start=126,
            booking_zone_end=129,
        ),
        created_at=managed.created_at,
        updated_at=managed.updated_at,
    )

    registry.replace(
        managed
    )

    lifecycle = PositionLifecycleManager(
        registry=registry
    )

    price_monitor = (
        OptionPositionPriceMonitor(
            registry=registry
        )
    )

    target_monitor = TargetTriggerMonitor(
        price_monitor=price_monitor,
        max_price_age=timedelta(
            seconds=5
        ),
    )

    stop_monitor = StopLossTriggerMonitor(
        price_monitor=price_monitor,
        max_price_age=timedelta(
            seconds=5
        ),
    )

    decision_engine = (
        PositionExitDecisionEngine()
    )

    pnl_tracker = PositionPnLTracker()

    pnl_tracker.register(
        position=managed,
        registered_at=INIT_TIME,
    )

    reentry_manager = (
        ReentryStateManager()
    )

    reentry_adapter = M04ReentryAdapter(
        manager=reentry_manager
    )

    reentry_sync = (
        ReentryRiskSynchronizer(
            registry=registry,
            reentry_port=reentry_adapter,
        )
    )

    provider = FakeExitProvider()

    exit_service = ExitExecutionService(
        provider=provider,
        duplicate_guard=DuplicateOrderGuard(),
        allow_live_exit_orders=True,
    )

    exit_integration = (
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

    daily_risk = DailyRiskManager(
        registry=registry
    )

    force_exit = ForceExitCoordinator(
        registry=registry
    )

    return {
        "registry": registry,
        "managed": managed,
        "lifecycle": lifecycle,
        "prices": price_monitor,
        "target_monitor": target_monitor,
        "stop_monitor": stop_monitor,
        "decision_engine": decision_engine,
        "pnl": pnl_tracker,
        "reentry_manager": reentry_manager,
        "reentry_sync": reentry_sync,
        "provider": provider,
        "exit_integration": exit_integration,
        "daily_risk": daily_risk,
        "force_exit": force_exit,
    }


def push_price(
    runtime,
    *,
    ltp: float,
    received_at: datetime,
) -> None:
    position = runtime[
        "registry"
    ].require(
        runtime["managed"].position_id
    )

    result = runtime[
        "prices"
    ].process_tick(
        OptionPriceTick(
            security_id=(
                position.security_id
            ),
            ltp=ltp,
            received_at=received_at,
        )
    )

    assert result.accepted is True

    runtime[
        "pnl"
    ].mark_to_market(
        position_id=position.position_id,
        ltp=ltp,
        marked_at=received_at,
    )


def test_entry_fill_initializes_open_managed_position() -> None:
    runtime = build_runtime()

    position = runtime[
        "registry"
    ].require(
        runtime["managed"].position_id
    )

    assert (
        position.state
        is ManagedPositionState.OPEN
    )

    assert position.open_quantity == 65
    assert position.closed_quantity == 0

    assert position.entry_price == 100


def test_stop_is_initialized_from_actual_entry_fill() -> None:
    runtime = build_runtime(
        filled_position=(
            make_filled_position(
                entry_price=100.65
            )
        )
    )

    position = runtime[
        "registry"
    ].require(
        FilledPositionId(
            "POS-M07-T20"
        )
    )

    assert position.stop_loss is not None

    assert (
        position.stop_loss.stop_price
        == 85.65
    )


def test_open_position_blocks_m04_reentry() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    result = runtime[
        "reentry_sync"
    ].sync_position_open(
        position_id=position.position_id,
        synchronized_at=INIT_TIME,
    )

    assert (
        result.status
        is ReentrySyncStatus
        .OPEN_POSITION_SYNCED
    )

    assert runtime[
        "reentry_manager"
    ].can_enter(
        EntryLevel.K5
    ) is False


def test_live_price_updates_unrealized_pnl() -> None:
    runtime = build_runtime()

    push_price(
        runtime,
        ltp=112,
        received_at=PRICE_TIME,
    )

    state = runtime[
        "pnl"
    ].require(
        runtime["managed"].position_id
    )

    assert state.open_quantity == 65

    assert (
        state.unrealized_pnl
        == 780
    )

    assert (
        state.total_pnl
        == 780
    )


def test_target_trigger_submits_one_m06_sell() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    runtime[
        "reentry_sync"
    ].sync_position_open(
        position_id=position.position_id,
        synchronized_at=INIT_TIME,
    )

    push_price(
        runtime,
        ltp=126,
        received_at=TARGET_TIME,
    )

    current = runtime[
        "registry"
    ].require(
        position.position_id
    )

    target = runtime[
        "target_monitor"
    ].evaluate(
        position=current,
        evaluated_at=TARGET_TIME,
    )

    stop = runtime[
        "stop_monitor"
    ].evaluate(
        position=current,
        evaluated_at=TARGET_TIME,
    )

    decision = runtime[
        "decision_engine"
    ].decide(
        position=current,
        target_result=target,
        stop_result=stop,
        force_exit=False,
        decided_at=TARGET_TIME,
    )

    assert decision.exit_required is True

    assert (
        decision.trigger
        is RiskTriggerType.TARGET
    )

    result = runtime[
        "exit_integration"
    ].execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=TARGET_TIME,
    )

    assert (
        result.status
        is M07ExitIntegrationStatus.SUBMITTED
    )

    assert runtime[
        "provider"
    ].submit_count == 1

    assert result.exit_plan is not None

    assert (
        result.exit_plan.reason
        is ExitReason.TARGET
    )

    assert (
        result.exit_plan.order_type
        is ExitOrderType.LIMIT
    )

    assert (
        result.exit_plan.exit_price
        == 126
    )

    stored = runtime[
        "registry"
    ].require(
        position.position_id
    )

    assert (
        stored.state
        is ManagedPositionState.EXIT_PENDING
    )


def test_partial_target_fill_keeps_reentry_blocked() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    runtime[
        "reentry_sync"
    ].sync_position_open(
        position_id=position.position_id,
        synchronized_at=INIT_TIME,
    )

    # Submit target exit.
    push_price(
        runtime,
        ltp=126,
        received_at=TARGET_TIME,
    )

    current = runtime[
        "registry"
    ].require(
        position.position_id
    )

    decision = runtime[
        "decision_engine"
    ].decide(
        position=current,
        target_result=(
            runtime[
                "target_monitor"
            ].evaluate(
                position=current,
                evaluated_at=TARGET_TIME,
            )
        ),
        stop_result=(
            runtime[
                "stop_monitor"
            ].evaluate(
                position=current,
                evaluated_at=TARGET_TIME,
            )
        ),
        force_exit=False,
        decided_at=TARGET_TIME,
    )

    runtime[
        "exit_integration"
    ].execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=TARGET_TIME,
    )

    # Actual broker partial fill.
    updated = runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=30,
        price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    assert (
        updated.state
        is ManagedPositionState
        .PARTIALLY_EXITED
    )

    assert updated.open_quantity == 35
    assert updated.closed_quantity == 30

    sync = runtime[
        "reentry_sync"
    ].sync_position_state(
        position_id=position.position_id,
        synchronized_at=PARTIAL_FILL_TIME,
    )

    assert (
        sync.status
        is ReentrySyncStatus.STILL_OPEN
    )

    assert sync.reentry_released is False

    assert runtime[
        "reentry_manager"
    ].can_enter(
        EntryLevel.K5
    ) is False


def test_partial_position_tracks_realized_and_unrealized_pnl() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=30,
        price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    mark_time = (
        PARTIAL_FILL_TIME
        + timedelta(seconds=1)
    )

    push_price(
        runtime,
        ltp=115,
        received_at=mark_time,
    )

    state = runtime[
        "pnl"
    ].require(
        position.position_id
    )

    assert state.open_quantity == 35
    assert state.closed_quantity == 30

    # 30 * (126 - 100)
    assert (
        state.realized_pnl
        == 780
    )

    # 35 * (115 - 100)
    assert (
        state.unrealized_pnl
        == 525
    )

    assert (
        state.total_pnl
        == 1305
    )


def test_final_fill_closes_position_and_releases_reentry() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    runtime[
        "reentry_sync"
    ].sync_position_open(
        position_id=position.position_id,
        synchronized_at=INIT_TIME,
    )

    # First partial fill.
    runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=30,
        price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    first_sync = runtime[
        "reentry_sync"
    ].sync_position_state(
        position_id=position.position_id,
        synchronized_at=PARTIAL_FILL_TIME,
    )

    assert first_sync.reentry_released is False

    # Final actual fill.
    closed = runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=35,
        fill_price=128,
        filled_at=FINAL_FILL_TIME,
    )

    runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=35,
        price=128,
        filled_at=FINAL_FILL_TIME,
    )

    assert (
        closed.state
        is ManagedPositionState.CLOSED
    )

    assert closed.open_quantity == 0
    assert closed.closed_quantity == 65

    final_sync = runtime[
        "reentry_sync"
    ].sync_position_state(
        position_id=position.position_id,
        synchronized_at=FINAL_FILL_TIME,
    )

    assert (
        final_sync.status
        is ReentrySyncStatus
        .CLOSED_POSITION_SYNCED
    )

    assert final_sync.reentry_released is True

    assert runtime[
        "reentry_manager"
    ].can_enter(
        EntryLevel.K5
    ) is True

    assert runtime[
        "reentry_manager"
    ].is_reentry(
        EntryLevel.K5
    ) is True


def test_final_realized_pnl_uses_actual_exit_fills() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=30,
        price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=35,
        fill_price=128,
        filled_at=FINAL_FILL_TIME,
    )

    state = runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=35,
        price=128,
        filled_at=FINAL_FILL_TIME,
    )

    # First:
    # (126 - 100) * 30 = 780
    #
    # Final:
    # (128 - 100) * 35 = 980
    #
    # Total:
    # 1760

    assert (
        state.realized_pnl
        == 1760
    )

    assert state.unrealized_pnl == 0
    assert state.total_pnl == 1760


def test_daily_risk_uses_final_realized_pnl() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=30,
        price=126,
        filled_at=PARTIAL_FILL_TIME,
    )

    runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=35,
        fill_price=128,
        filled_at=FINAL_FILL_TIME,
    )

    runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=35,
        price=128,
        filled_at=FINAL_FILL_TIME,
    )

    daily = runtime[
        "daily_risk"
    ].build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls=(
            runtime[
                "pnl"
            ].pnl_map()
        ),
        captured_at=FINAL_FILL_TIME,
    )

    assert daily.open_positions == 0
    assert daily.closed_positions == 1
    assert daily.open_quantity == 0

    assert (
        daily.realized_pnl
        == 1760
    )

    assert daily.unrealized_pnl == 0

    assert (
        daily.total_pnl
        == 1760
    )


def test_stop_loss_full_lifecycle() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    runtime[
        "reentry_sync"
    ].sync_position_open(
        position_id=position.position_id,
        synchronized_at=INIT_TIME,
    )

    stop_time = (
        ENTRY_TIME
        + timedelta(minutes=20)
    )

    push_price(
        runtime,
        ltp=85,
        received_at=stop_time,
    )

    current = runtime[
        "registry"
    ].require(
        position.position_id
    )

    target = runtime[
        "target_monitor"
    ].evaluate(
        position=current,
        evaluated_at=stop_time,
    )

    stop = runtime[
        "stop_monitor"
    ].evaluate(
        position=current,
        evaluated_at=stop_time,
    )

    assert stop.triggered is True
    assert target.triggered is False

    decision = runtime[
        "decision_engine"
    ].decide(
        position=current,
        target_result=target,
        stop_result=stop,
        force_exit=False,
        decided_at=stop_time,
    )

    assert (
        decision.trigger
        is RiskTriggerType.STOP_LOSS
    )

    execution = runtime[
        "exit_integration"
    ].execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=stop_time,
    )

    assert execution.submitted is True

    assert execution.exit_plan is not None

    assert (
        execution.exit_plan.reason
        is ExitReason.STOP_LOSS
    )

    assert (
        execution.exit_plan.order_type
        is ExitOrderType.MARKET
    )

    fill_time = (
        stop_time
        + timedelta(seconds=1)
    )

    closed = runtime[
        "lifecycle"
    ].apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=65,
        fill_price=84,
        filled_at=fill_time,
    )

    pnl = runtime[
        "pnl"
    ].record_exit_fill(
        position_id=position.position_id,
        quantity=65,
        price=84,
        filled_at=fill_time,
    )

    assert (
        closed.state
        is ManagedPositionState.CLOSED
    )

    # Actual loss:
    # (84 - 100) * 65
    assert (
        pnl.realized_pnl
        == -1040
    )

    sync = runtime[
        "reentry_sync"
    ].sync_position_state(
        position_id=position.position_id,
        synchronized_at=fill_time,
    )

    assert sync.reentry_released is True


def test_1515_open_position_routes_to_force_exit() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    instruction = runtime[
        "force_exit"
    ].evaluate_position(
        position=position,
        evaluated_at=FORCE_EXIT_TIME,
    )

    assert (
        instruction.action
        is ForceExitAction.NEW_FORCE_EXIT
    )

    assert instruction.quantity == 65

    decision = runtime[
        "decision_engine"
    ].decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_EXIT_TIME,
    )

    assert (
        decision.trigger
        is RiskTriggerType.FORCE_EXIT
    )

    result = runtime[
        "exit_integration"
    ].execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=FORCE_EXIT_TIME,
    )

    assert result.submitted is True

    assert result.exit_plan is not None

    assert (
        result.exit_plan.reason
        is ExitReason.FORCE_EXIT
    )

    assert (
        result.exit_plan.order_type
        is ExitOrderType.MARKET
    )

    assert runtime[
        "provider"
    ].submit_count == 1


def test_1515_existing_pending_exit_does_not_submit_duplicate_sell() -> None:
    runtime = build_runtime()

    position = runtime["managed"]

    # First submit TARGET exit before 15:15.
    push_price(
        runtime,
        ltp=126,
        received_at=TARGET_TIME,
    )

    current = runtime[
        "registry"
    ].require(
        position.position_id
    )

    decision = runtime[
        "decision_engine"
    ].decide(
        position=current,
        target_result=(
            runtime[
                "target_monitor"
            ].evaluate(
                position=current,
                evaluated_at=TARGET_TIME,
            )
        ),
        stop_result=(
            runtime[
                "stop_monitor"
            ].evaluate(
                position=current,
                evaluated_at=TARGET_TIME,
            )
        ),
        force_exit=False,
        decided_at=TARGET_TIME,
    )

    runtime[
        "exit_integration"
    ].execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=TARGET_TIME,
    )

    assert runtime[
        "provider"
    ].submit_count == 1

    pending = runtime[
        "registry"
    ].require(
        position.position_id
    )

    assert (
        pending.state
        is ManagedPositionState.EXIT_PENDING
    )

    instruction = runtime[
        "force_exit"
    ].evaluate_position(
        position=pending,
        evaluated_at=FORCE_EXIT_TIME,
    )

    assert (
        instruction.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert instruction.force_exit_required is False

    # T14 must not submit another SELL.
    assert runtime[
        "provider"
    ].submit_count == 1