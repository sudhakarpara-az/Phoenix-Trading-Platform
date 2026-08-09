from datetime import date, datetime

from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
)
from src.execution.execution_service import (
    ExecutionService,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
    ExecutionResult,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderSnapshot,
)
from src.execution.exit_execution_service import (
    ExitExecutionDecision,
    ExitExecutionService,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.exit_reconciliation_service import (
    ExitReconciliationDecision,
    ExitReconciliationService,
)
from src.execution.filled_position_builder import (
    FilledPositionBuilder,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
    IdempotencyKey,
    IdempotencyState,
)
from src.execution.order_eligibility_validator import (
    OrderEligibilityContext,
    OrderEligibilityValidator,
)
from src.execution.order_pricing_policy import (
    OrderPricingConfig,
    OrderPricingPolicy,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitReason,
    PositionState,
)
from src.execution.quantity_policy import (
    QuantityPolicy,
)
from src.execution.target_booking_policy import (
    TargetBookingMode,
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
from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
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

ENTRY_REQUEST_TIME = datetime(
    2026,
    8,
    7,
    14,
    30,
)

ENTRY_FILL_TIME = datetime(
    2026,
    8,
    7,
    14,
    30,
    5,
)

TARGET_TIME = datetime(
    2026,
    8,
    7,
    14,
    31,
)

FORCE_EXIT_TIME = datetime(
    2026,
    8,
    7,
    15,
    15,
)


class LifecycleFakeBroker(
    BrokerExecutionProvider,
    ExitExecutionProvider,
):
    """
    Full M06 integration fake.

    ENTRY behavior:
        BUY order fills immediately at configured average price.

    EXIT behavior:
        First SELL submission = target order remains OPEN.

        During 15:15 reconciliation:
            status may report partial fill.
            cancellation succeeds.
            second status confirms CANCELLED.

        Second SELL submission = force-exit MARKET order FILLS.

    Absolutely no external broker API is called.
    """

    def __init__(
        self,
        *,
        entry_average_price: float = 100.65,
        target_initial_filled: int = 0,
        target_final_filled: int = 0,
    ) -> None:
        self.entry_average_price = (
            entry_average_price
        )

        self.target_initial_filled = (
            target_initial_filled
        )

        self.target_final_filled = (
            target_final_filled
        )

        self.entry_submit_count = 0
        self.exit_submit_count = 0
        self.exit_cancel_count = 0
        self.exit_status_count = 0

        self.last_entry_intent = None

        self.submitted_exit_intents = []

        self.entry_reference = (
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="ENTRY-001",
            )
        )

        self.target_reference = (
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="TARGET-001",
            )
        )

        self.force_exit_reference = (
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="FORCE-001",
            )
        )

    @property
    def broker_name(self) -> str:
        return "FAKE"

    # --------------------------------------------------
    # ENTRY provider
    # --------------------------------------------------

    def submit_order(
        self,
        intent,
    ) -> ExecutionResult:
        self.entry_submit_count += 1

        self.last_entry_intent = intent

        return ExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.FILLED,
            broker_reference=(
                self.entry_reference
            ),
            submitted_at=ENTRY_FILL_TIME,
        )

    def cancel_order(
        self,
        broker_reference,
    ) -> BrokerCancellationResult:
        return BrokerCancellationResult(
            broker_reference=broker_reference,
            success=True,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=ENTRY_FILL_TIME,
        )

    def get_order_status(
        self,
        broker_reference,
    ) -> BrokerOrderSnapshot:
        return BrokerOrderSnapshot(
            broker_reference=(
                broker_reference
            ),
            status=BrokerOrderStatus.FILLED,
            quantity=(
                self.last_entry_intent.quantity
            ),
            filled_quantity=(
                self.last_entry_intent.quantity
            ),
            average_price=(
                self.entry_average_price
            ),
            updated_at=ENTRY_FILL_TIME,
        )

    # --------------------------------------------------
    # EXIT provider
    # --------------------------------------------------

    def submit_exit(
        self,
        intent,
    ) -> ExitExecutionResult:
        self.exit_submit_count += 1

        self.submitted_exit_intents.append(
            intent
        )

        # First SELL = target LIMIT order.
        if self.exit_submit_count == 1:
            return ExitExecutionResult(
                intent_id=intent.intent_id,
                success=True,
                status=BrokerOrderStatus.OPEN,
                broker_reference=(
                    self.target_reference
                ),
                submitted_at=TARGET_TIME,
            )

        # Second SELL = 15:15 force-exit MARKET.
        return ExitExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.FILLED,
            broker_reference=(
                self.force_exit_reference
            ),
            submitted_at=FORCE_EXIT_TIME,
        )

    def cancel_exit(
        self,
        broker_reference,
    ) -> ExitCancellationResult:
        self.exit_cancel_count += 1

        return ExitCancellationResult(
            broker_reference=broker_reference,
            success=True,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=FORCE_EXIT_TIME,
        )

    def get_exit_status(
        self,
        broker_reference,
    ) -> ExitOrderSnapshot:
        self.exit_status_count += 1

        if self.exit_status_count == 1:
            status = (
                BrokerOrderStatus.PARTIALLY_FILLED
                if self.target_initial_filled > 0
                else BrokerOrderStatus.OPEN
            )

            filled_quantity = (
                self.target_initial_filled
            )

        else:
            status = (
                BrokerOrderStatus.CANCELLED
            )

            filled_quantity = (
                self.target_final_filled
            )

        average_price = (
            126.0
            if filled_quantity > 0
            else None
        )

        return ExitOrderSnapshot(
            broker_reference=(
                broker_reference
            ),
            status=status,
            quantity=(
                self.last_entry_intent.quantity
            ),
            filled_quantity=(
                filled_quantity
            ),
            average_price=average_price,
            updated_at=FORCE_EXIT_TIME,
        )


def make_signal(
    *,
    signal_id: str = "SIG-M06-T21",
    direction: SignalDirection = (
        SignalDirection.CALL
    ),
) -> TradingSignal:
    side = (
        "CE"
        if direction is SignalDirection.CALL
        else "PE"
    )

    return TradingSignal(
        signal_id=SignalId(
            signal_id
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=direction,
        instrument_security_id="41009",
        instrument_symbol=(
            "NIFTY50-20260811-"
            f"24450-{side}"
        ),
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=ENTRY_REQUEST_TIME,
    )


def make_selected_option(
    *,
    option_type: OptionType = OptionType.CALL,
    ltp: float = 100.0,
    lot_size: int = 65,
) -> SelectedOption:
    side = (
        "CE"
        if option_type is OptionType.CALL
        else "PE"
    )

    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-"
                    f"24450-{side}"
                ),
                security_id="41009",
                option_type=option_type,
                strike=24450.0,
                expiry=EXPIRY,
                lot_size=lot_size,
            ),
            quote=OptionQuote(
                ltp=ltp,
                bid=ltp - 0.05,
                ask=ltp + 0.05,
                volume=10000,
                open_interest=50000,
                received_at=ENTRY_REQUEST_TIME,
            ),
            greeks=OptionGreeks(
                delta=(
                    0.64
                    if option_type
                    is OptionType.CALL
                    else -0.64
                ),
                calculated_at=(
                    ENTRY_REQUEST_TIME
                ),
            ),
        ),
        selected_at=ENTRY_REQUEST_TIME,
        selection_delta_target=0.64,
    )


def make_entry_service(
    broker,
):
    state_machine = OrderStateMachine()

    service = ExecutionService(
        pricing_policy=OrderPricingPolicy(
            OrderPricingConfig(
                entry_buffer_points=1.0,
                tick_size=0.05,
            )
        ),
        quantity_policy=QuantityPolicy(),
        eligibility_validator=(
            OrderEligibilityValidator()
        ),
        state_machine=state_machine,
        broker_provider=broker,
        allow_live_orders=True,
    )

    return service, state_machine


def execute_filled_entry(
    *,
    broker,
    quantity: int = 65,
):
    service, state_machine = (
        make_entry_service(
            broker
        )
    )

    result = service.execute(
        signal=make_signal(),
        selected_option=(
            make_selected_option()
        ),
        quantity=quantity,
        execution_mode=ExecutionMode.LIVE,
        requested_at=ENTRY_REQUEST_TIME,
        context=OrderEligibilityContext(),
    )

    assert result.intent is not None

    assert result.execution_result is not None

    snapshot = broker.get_order_status(
        result.execution_result
        .broker_reference
    )

    position = FilledPositionBuilder().build(
        intent=result.intent,
        broker_snapshot=snapshot,
    )

    return (
        result,
        position,
        state_machine,
    )


def make_target_exit_plan(
    *,
    position,
    mapped_target_price: float,
):
    return ExitPlanBuilder(
        TargetBookingPolicy()
    ).build_target_exit(
        position=position,
        mapped_target_price=(
            mapped_target_price
        ),
        created_at=TARGET_TIME,
    )


def make_exit_services(
    *,
    broker,
):
    guard = DuplicateOrderGuard()

    exit_service = ExitExecutionService(
        provider=broker,
        duplicate_guard=guard,
        allow_live_exit_orders=True,
    )

    reconciliation_service = (
        ExitReconciliationService(
            provider=broker,
            exit_plan_builder=(
                ExitPlanBuilder(
                    TargetBookingPolicy()
                )
            ),
            duplicate_guard=guard,
        )
    )

    return (
        exit_service,
        reconciliation_service,
        guard,
    )


def test_complete_entry_fill_target_creation() -> None:
    broker = LifecycleFakeBroker(
        entry_average_price=100.65
    )

    (
        entry_result,
        position,
        state_machine,
    ) = execute_filled_entry(
        broker=broker
    )

    assert entry_result.accepted is True
    assert entry_result.submitted is True

    assert broker.entry_submit_count == 1

    assert entry_result.intent is not None

    assert (
        entry_result.intent.limit_price
        == 101.0
    )

    assert (
        state_machine.get_state(
            entry_result.intent.intent_id
        )
        is OrderLifecycleState.FILLED
    )

    assert (
        position.state
        is PositionState.OPEN
    )

    # Most important fill-price invariant:
    assert (
        position.entry_price
        == 100.65
    )

    assert (
        position.entry_price
        != entry_result.intent.limit_price
    )


def test_near_target_is_built_from_actual_position() -> None:
    broker = LifecycleFakeBroker(
        entry_average_price=100.0
    )

    (
        _,
        position,
        _,
    ) = execute_filled_entry(
        broker=broker
    )

    target_plan = make_target_exit_plan(
        position=position,
        mapped_target_price=129.0,
    )

    assert (
        target_plan.reason
        is ExitReason.TARGET
    )

    assert (
        target_plan.order_type
        is ExitOrderType.LIMIT
    )

    assert (
        target_plan.exit_price
        == 126.0
    )

    assert target_plan.target_plan is not None

    assert (
        target_plan.target_plan.mode
        is TargetBookingMode.NEAR_KS_TARGET
    )

    assert (
        target_plan.target_plan
        .booking_zone_start
        == 126.0
    )

    assert (
        target_plan.target_plan
        .booking_zone_end
        == 129.0
    )


def test_far_target_uses_actual_fill_plus_30() -> None:
    broker = LifecycleFakeBroker(
        entry_average_price=100.65
    )

    (
        _,
        position,
        _,
    ) = execute_filled_entry(
        broker=broker
    )

    target_plan = make_target_exit_plan(
        position=position,
        mapped_target_price=140.0,
    )

    assert (
        target_plan.exit_price
        == 130.65
    )

    assert target_plan.target_plan is not None

    assert (
        target_plan.target_plan.mode
        is TargetBookingMode.FIXED_30_POINTS
    )


def test_target_exit_is_submitted_only_once() -> None:
    broker = LifecycleFakeBroker(
        entry_average_price=100.0
    )

    (
        _,
        position,
        _,
    ) = execute_filled_entry(
        broker=broker
    )

    target_plan = make_target_exit_plan(
        position=position,
        mapped_target_price=129.0,
    )

    (
        exit_service,
        _,
        guard,
    ) = make_exit_services(
        broker=broker
    )

    first = exit_service.execute(
        exit_plan=target_plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=TARGET_TIME,
    )

    second = exit_service.execute(
        exit_plan=target_plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=TARGET_TIME,
    )

    assert first.accepted is True

    assert (
        first.execution_result
        is not None
    )

    assert (
        first.execution_result.status
        is BrokerOrderStatus.OPEN
    )

    assert second.accepted is False

    assert (
        second.decision
        is ExitExecutionDecision.DUPLICATE_EXIT
    )

    assert (
        broker.exit_submit_count
        == 1
    )

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{position.position_id.value}"
    )

    assert (
        guard.get(key).state
        is IdempotencyState.SUBMITTED
    )


def test_full_target_to_1515_force_exit_lifecycle() -> None:
    """
    Main T21 lifecycle.

    Position = 65

    Target SELL = OPEN

    15:15:
        cancel target
        confirm CANCELLED
        remaining = 65

    Submit force MARKET SELL = FILLED
    """

    broker = LifecycleFakeBroker(
        entry_average_price=100.0,
        target_initial_filled=0,
        target_final_filled=0,
    )

    (
        entry_result,
        position,
        _,
    ) = execute_filled_entry(
        broker=broker
    )

    assert entry_result.intent is not None

    target_plan = make_target_exit_plan(
        position=position,
        mapped_target_price=129.0,
    )

    (
        exit_service,
        reconciliation_service,
        guard,
    ) = make_exit_services(
        broker=broker
    )

    # --------------------------------------------------
    # Submit target SELL
    # --------------------------------------------------

    target_result = exit_service.execute(
        exit_plan=target_plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=TARGET_TIME,
    )

    assert target_result.accepted is True
    assert target_result.intent is not None

    assert (
        target_result.execution_result
        is not None
    )

    assert (
        target_result.execution_result.status
        is BrokerOrderStatus.OPEN
    )

    assert (
        target_result.intent.order_type
        is ExitOrderType.LIMIT
    )

    assert (
        target_result.intent.price
        == 126.0
    )

    target_reference = (
        target_result
        .execution_result
        .broker_reference
    )

    assert target_reference is not None

    # --------------------------------------------------
    # 15:15 reconciliation
    # --------------------------------------------------

    reconciliation = (
        reconciliation_service
        .reconcile_for_force_exit(
            position=position,
            active_exit_intent=(
                target_result.intent
            ),
            broker_reference=(
                target_reference
            ),
            requested_at=FORCE_EXIT_TIME,
        )
    )

    assert (
        reconciliation.decision
        is ExitReconciliationDecision
        .FORCE_EXIT_READY
    )

    assert (
        broker.exit_cancel_count
        == 1
    )

    assert (
        broker.exit_status_count
        == 2
    )

    assert (
        reconciliation.filled_quantity
        == 0
    )

    assert (
        reconciliation.remaining_quantity
        == 65
    )

    assert (
        reconciliation.force_exit_plan
        is not None
    )

    assert (
        reconciliation
        .force_exit_plan
        .reason
        is ExitReason.FORCE_EXIT
    )

    assert (
        reconciliation
        .force_exit_plan
        .order_type
        is ExitOrderType.MARKET
    )

    # --------------------------------------------------
    # Existing target lock must now be safely released.
    # --------------------------------------------------

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{position.position_id.value}"
    )

    assert (
        guard.get(key).state
        is IdempotencyState.RELEASED
    )

    # --------------------------------------------------
    # Submit replacement MARKET SELL
    # --------------------------------------------------

    force_result = exit_service.execute(
        exit_plan=(
            reconciliation.force_exit_plan
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=FORCE_EXIT_TIME,
    )

    assert force_result.accepted is True

    assert force_result.intent is not None

    assert (
        force_result.intent.order_type
        is ExitOrderType.MARKET
    )

    assert force_result.intent.price is None

    assert (
        force_result.intent.quantity
        == 65
    )

    assert (
        force_result.execution_result
        is not None
    )

    assert (
        force_result.execution_result.status
        is BrokerOrderStatus.FILLED
    )

    # Target + force exit:
    assert (
        broker.exit_submit_count
        == 2
    )

    # Final position-level execution lock is completed.
    assert (
        guard.get(key).state
        is IdempotencyState.COMPLETED
    )


def test_partial_target_fill_force_exits_only_remaining_quantity() -> None:
    """
    Position = 65

    Before cancellation:
        target filled 20

    During cancellation race:
        additional 10 fill

    Final target state:
        CANCELLED
        filled = 30

    Force exit must sell ONLY 35.
    """

    broker = LifecycleFakeBroker(
        entry_average_price=100.0,
        target_initial_filled=20,
        target_final_filled=30,
    )

    (
        _,
        position,
        _,
    ) = execute_filled_entry(
        broker=broker
    )

    target_plan = make_target_exit_plan(
        position=position,
        mapped_target_price=129.0,
    )

    (
        exit_service,
        reconciliation_service,
        guard,
    ) = make_exit_services(
        broker=broker
    )

    target_result = exit_service.execute(
        exit_plan=target_plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=TARGET_TIME,
    )

    assert target_result.intent is not None
    assert target_result.execution_result is not None

    reference = (
        target_result
        .execution_result
        .broker_reference
    )

    assert reference is not None

    reconciliation = (
        reconciliation_service
        .reconcile_for_force_exit(
            position=position,
            active_exit_intent=(
                target_result.intent
            ),
            broker_reference=reference,
            requested_at=FORCE_EXIT_TIME,
        )
    )

    assert (
        reconciliation.decision
        is ExitReconciliationDecision
        .FORCE_EXIT_READY
    )

    # Critical race result:
    assert (
        reconciliation.filled_quantity
        == 30
    )

    assert (
        reconciliation.remaining_quantity
        == 35
    )

    assert (
        reconciliation.force_exit_plan
        is not None
    )

    assert (
        reconciliation
        .force_exit_plan
        .quantity
        == 35
    )

    force_result = exit_service.execute(
        exit_plan=(
            reconciliation.force_exit_plan
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=FORCE_EXIT_TIME,
    )

    assert force_result.accepted is True

    assert force_result.intent is not None

    assert (
        force_result.intent.quantity
        == 35
    )

    assert (
        force_result.intent.order_type
        is ExitOrderType.MARKET
    )

    assert (
        broker.exit_submit_count
        == 2
    )

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{position.position_id.value}"
    )

    assert (
        guard.get(key).state
        is IdempotencyState.COMPLETED
    )


def test_target_fills_during_cancel_race_no_force_sell_is_sent() -> None:
    """
    Protects against:

        cancellation request
            ↓
        target fills before cancellation settles
            ↓
        Phoenix must NOT send another MARKET SELL.
    """

    class FillDuringCancelBroker(
        LifecycleFakeBroker
    ):
        def get_exit_status(
            self,
            broker_reference,
        ) -> ExitOrderSnapshot:
            self.exit_status_count += 1

            if self.exit_status_count == 1:
                return ExitOrderSnapshot(
                    broker_reference=(
                        broker_reference
                    ),
                    status=BrokerOrderStatus.OPEN,
                    quantity=65,
                    filled_quantity=0,
                    average_price=None,
                    updated_at=FORCE_EXIT_TIME,
                )

            return ExitOrderSnapshot(
                broker_reference=(
                    broker_reference
                ),
                status=BrokerOrderStatus.FILLED,
                quantity=65,
                filled_quantity=65,
                average_price=126.0,
                updated_at=FORCE_EXIT_TIME,
            )

    broker = FillDuringCancelBroker(
        entry_average_price=100.0
    )

    (
        _,
        position,
        _,
    ) = execute_filled_entry(
        broker=broker
    )

    target_plan = make_target_exit_plan(
        position=position,
        mapped_target_price=129.0,
    )

    (
        exit_service,
        reconciliation_service,
        guard,
    ) = make_exit_services(
        broker=broker
    )

    target_result = exit_service.execute(
        exit_plan=target_plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=TARGET_TIME,
    )

    assert target_result.intent is not None
    assert target_result.execution_result is not None

    reference = (
        target_result
        .execution_result
        .broker_reference
    )

    assert reference is not None

    reconciliation = (
        reconciliation_service
        .reconcile_for_force_exit(
            position=position,
            active_exit_intent=(
                target_result.intent
            ),
            broker_reference=reference,
            requested_at=FORCE_EXIT_TIME,
        )
    )

    assert (
        reconciliation.decision
        is ExitReconciliationDecision
        .POSITION_ALREADY_CLOSED
    )

    assert (
        reconciliation.remaining_quantity
        == 0
    )

    assert (
        reconciliation.force_exit_plan
        is None
    )

    # Only target SELL was submitted.
    assert (
        broker.exit_submit_count
        == 1
    )

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{position.position_id.value}"
    )

    assert (
        guard.get(key).state
        is IdempotencyState.COMPLETED
    )