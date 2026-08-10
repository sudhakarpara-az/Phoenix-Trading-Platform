from datetime import date, datetime

import pytest

from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
)
from src.execution.execution_service import (
    EntrySubmissionUncertainError,
    ExecutionService,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
    ExecutionResult,
    OrderIntent,
    OrderIntentId,
    OrderType,
    TransactionType,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderIntent,
    ExitOrderIntentId,
    ExitOrderSnapshot,
    ExitTransactionType,
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
    OrderEligibilityReason,
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
    ExitPlan,
    ExitReason,
    FilledPosition,
    FilledPositionId,
)
from src.execution.quantity_policy import (
    QuantityPolicy,
)
from src.execution.target_booking_policy import (
    TargetBookingMode,
    TargetBookingPlan,
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

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)

FORCE_TIME = datetime(
    2026,
    8,
    7,
    15,
    15,
)


def make_signal(
    signal_id: str = "SIG-T22",
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(signal_id),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        instrument_security_id="41009",
        instrument_symbol="NIFTY50-20260811-24450-CE",
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )


def make_option(
    *,
    ltp: float = 100.0,
    lot_size: int = 65,
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-24450-CE"
                ),
                security_id="41009",
                option_type=OptionType.CALL,
                strike=24450.0,
                expiry=EXPIRY,
                lot_size=lot_size,
            ),
            quote=OptionQuote(
                ltp=ltp,
                bid=max(ltp - 0.05, 0.05),
                ask=ltp + 0.05,
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


def make_entry_intent(
    *,
    quantity: int = 65,
) -> OrderIntent:
    return OrderIntent(
        intent_id=OrderIntentId(
            "ORD-T22"
        ),
        signal=make_signal(),
        selected_option=make_option(),
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=101.0,
        execution_mode=ExecutionMode.LIVE,
        created_at=NOW,
    )


def make_filled_position(
    *,
    quantity: int = 65,
    entry_price: float = 100.0,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-T22"
        ),
        signal_id=SignalId(
            "SIG-T22"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-T22"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-T22",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )


def make_target_plan() -> TargetBookingPlan:
    return TargetBookingPlan(
        entry_price=100.0,
        mapped_target_price=129.0,
        target_distance_points=29.0,
        executable_target_price=126.0,
        booking_zone_start=126.0,
        booking_zone_end=129.0,
        mode=TargetBookingMode.NEAR_KS_TARGET,
        tick_size=0.05,
    )


def make_exit_plan(
    *,
    position_id: str = "POS-T22",
    quantity: int = 65,
) -> ExitPlan:
    return ExitPlan(
        position_id=FilledPositionId(
            position_id
        ),
        security_id="41009",
        symbol=(
            "NIFTY50-20260811-24450-CE"
        ),
        option_type=OptionType.CALL,
        quantity=quantity,
        reason=ExitReason.TARGET,
        order_type=ExitOrderType.LIMIT,
        mapped_target_price=129.0,
        target_plan=make_target_plan(),
        exit_price=126.0,
        created_at=NOW,
    )


class EntryBrokerRaises(
    BrokerExecutionProvider
):
    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_order(
        self,
        intent,
    ) -> ExecutionResult:
        raise RuntimeError(
            "simulated network timeout"
        )

    def cancel_order(
        self,
        broker_reference,
    ) -> BrokerCancellationResult:
        raise NotImplementedError

    def get_order_status(
        self,
        broker_reference,
    ) -> BrokerOrderSnapshot:
        raise NotImplementedError


class ExitBrokerRaises(
    ExitExecutionProvider
):
    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent,
    ) -> ExitExecutionResult:
        raise RuntimeError(
            "simulated SELL timeout"
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


class ReconciliationBroker(
    ExitExecutionProvider
):
    def __init__(
        self,
        *,
        first_status=BrokerOrderStatus.OPEN,
        first_filled=0,
        final_status=BrokerOrderStatus.CANCELLED,
        final_filled=0,
        cancel_success=True,
    ) -> None:
        self.first_status = first_status
        self.first_filled = first_filled
        self.final_status = final_status
        self.final_filled = final_filled
        self.cancel_success = cancel_success

        self.status_calls = 0
        self.cancel_calls = 0

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent,
    ) -> ExitExecutionResult:
        raise AssertionError(
            "reconciliation must not submit SELL"
        )

    def cancel_exit(
        self,
        broker_reference,
    ) -> ExitCancellationResult:
        self.cancel_calls += 1

        return ExitCancellationResult(
            broker_reference=broker_reference,
            success=self.cancel_success,
            status=(
                BrokerOrderStatus.CANCELLED
                if self.cancel_success
                else BrokerOrderStatus.OPEN
            ),
            cancelled_at=FORCE_TIME,
            message=(
                None
                if self.cancel_success
                else "simulated cancellation failure"
            ),
        )

    def get_exit_status(
        self,
        broker_reference,
    ) -> ExitOrderSnapshot:
        self.status_calls += 1

        if self.status_calls == 1:
            status = self.first_status
            filled = self.first_filled
        else:
            status = self.final_status
            filled = self.final_filled

        return ExitOrderSnapshot(
            broker_reference=broker_reference,
            status=status,
            quantity=65,
            filled_quantity=filled,
            average_price=(
                126.0
                if filled > 0
                else None
            ),
            updated_at=FORCE_TIME,
        )


def make_entry_service(
    provider,
    *,
    allow_live_orders=True,
):
    state_machine = OrderStateMachine()
    guard = DuplicateOrderGuard()

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
        broker_provider=provider,
        idempotency_guard=guard,
        allow_live_orders=allow_live_orders,
    )

    return (
        service,
        state_machine,
        guard,
    )


def make_active_exit_context(
    guard,
    position,
):
    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{position.position_id.value}"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent_id(
        key=key,
        intent_id="EXIT-T22",
        changed_at=NOW,
    )

    guard.mark_submitted(
        key=key,
        changed_at=NOW,
    )

    intent = ExitOrderIntent(
        intent_id=ExitOrderIntentId(
            "EXIT-T22"
        ),
        position_id=position.position_id,
        security_id=position.security_id,
        symbol=position.symbol,
        option_type=position.option_type,
        transaction_type=(
            ExitTransactionType.SELL
        ),
        order_type=ExitOrderType.LIMIT,
        quantity=position.quantity,
        price=126.0,
        reason=ExitReason.TARGET,
        created_at=NOW,
    )

    return key, intent


def test_invalid_entry_quantity_fails_before_broker() -> None:
    provider = EntryBrokerRaises()

    (
        service,
        state_machine,
        guard,
    ) = make_entry_service(
        provider
    )

    signal = make_signal(
        "SIG-INVALID-QTY-T22"
    )

    result = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=100,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.accepted is False

    assert (
        result.eligibility.reason
        is OrderEligibilityReason.INVALID_QUANTITY
    )

    assert result.intent is None
    assert state_machine.count() == 0

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert guard.is_blocked(
        key
    ) is False


def test_entry_broker_exception_keeps_idempotency_blocked() -> None:
    provider = EntryBrokerRaises()

    (
        service,
        state_machine,
        guard,
    ) = make_entry_service(
        provider
    )

    signal = make_signal(
        "SIG-BROKER-FAIL-T22"
    )

    with pytest.raises(
        EntrySubmissionUncertainError,
        match="simulated network timeout",
    ) as exc_info:
        service.execute(
            signal=signal,
            selected_option=make_option(),
            quantity=65,
            execution_mode=ExecutionMode.LIVE,
            requested_at=NOW,
            context=OrderEligibilityContext(),
        )

    uncertain = exc_info.value

    assert (
        uncertain.intent.signal.signal_id
        == signal.signal_id
    )

    assert (
        uncertain.intent.selected_option.security_id
        == make_option().security_id
    )

    assert isinstance(
        uncertain.cause,
        RuntimeError,
    )

    assert (
        str(uncertain.cause)
        == "simulated network timeout"
    )

    assert (
        state_machine.get_state(
            uncertain.intent.intent_id
        )
        is OrderLifecycleState
        .RECONCILIATION_REQUIRED
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    record = guard.get(
        key
    )

    assert record is not None

    assert (
        record.intent_id
        == uncertain.intent.intent_id.value
    )

    assert (
        record.state
        is IdempotencyState.SUBMITTED
    )


def test_partial_entry_fill_cannot_create_full_position() -> None:
    builder = FilledPositionBuilder()

    snapshot = BrokerOrderSnapshot(
        broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-T22",
            )
        ),
        status=(
            BrokerOrderStatus.PARTIALLY_FILLED
        ),
        quantity=65,
        filled_quantity=30,
        average_price=100.50,
        updated_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="can only be built from FILLED",
    ):
        builder.build(
            intent=make_entry_intent(),
            broker_snapshot=snapshot,
        )


def test_filled_snapshot_without_average_price_rejected() -> None:
    builder = FilledPositionBuilder()

    snapshot = BrokerOrderSnapshot(
        broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-T22",
            )
        ),
        status=BrokerOrderStatus.FILLED,
        quantity=65,
        filled_quantity=65,
        average_price=None,
        updated_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="must contain average fill price",
    ):
        builder.build(
            intent=make_entry_intent(),
            broker_snapshot=snapshot,
        )


def test_dry_run_snapshot_cannot_create_real_position() -> None:
    builder = FilledPositionBuilder()

    snapshot = BrokerOrderSnapshot(
        broker_reference=(
            BrokerOrderReference(
                broker_name="DRY_RUN",
                order_id="DRY-ENTRY",
            )
        ),
        status=BrokerOrderStatus.FILLED,
        quantity=65,
        filled_quantity=65,
        average_price=100.0,
        updated_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="dry-run order cannot create real filled position",
    ):
        builder.build(
            intent=make_entry_intent(),
            broker_snapshot=snapshot,
        )


def test_target_equal_to_entry_is_rejected() -> None:
    policy = TargetBookingPolicy()

    with pytest.raises(
        ValueError,
        match="mapped_target_price must be above entry_price",
    ):
        policy.calculate(
            entry_price=100,
            mapped_target_price=100,
        )


def test_target_too_close_for_buffer_is_rejected() -> None:
    policy = TargetBookingPolicy()

    with pytest.raises(
        ValueError,
        match="mapped target is too close to entry",
    ):
        policy.calculate(
            entry_price=100,
            mapped_target_price=102,
        )


def test_force_exit_quantity_cannot_exceed_position() -> None:
    builder = ExitPlanBuilder(
        TargetBookingPolicy()
    )

    position = make_filled_position(
        quantity=65
    )

    with pytest.raises(
        ValueError,
        match="force exit quantity cannot exceed position quantity",
    ):
        builder.build_force_exit(
            position=position,
            created_at=FORCE_TIME,
            quantity=130,
        )


def test_duplicate_exit_is_blocked() -> None:
    class OpenExitProvider(
        ExitExecutionProvider
    ):
        def __init__(self):
            self.submit_count = 0

        @property
        def broker_name(self):
            return "FAKE"

        def submit_exit(
            self,
            intent,
        ):
            self.submit_count += 1

            return ExitExecutionResult(
                intent_id=intent.intent_id,
                success=True,
                status=BrokerOrderStatus.OPEN,
                broker_reference=(
                    BrokerOrderReference(
                        broker_name="FAKE",
                        order_id="EXIT-T22",
                    )
                ),
                submitted_at=NOW,
            )

        def cancel_exit(
            self,
            broker_reference,
        ):
            raise NotImplementedError

        def get_exit_status(
            self,
            broker_reference,
        ):
            raise NotImplementedError

    provider = OpenExitProvider()

    service = ExitExecutionService(
        provider=provider,
        allow_live_exit_orders=True,
    )

    plan = make_exit_plan()

    first = service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    second = service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert first.accepted is True

    assert second.accepted is False

    assert (
        second.decision
        is ExitExecutionDecision.DUPLICATE_EXIT
    )

    assert provider.submit_count == 1


def test_exit_broker_exception_keeps_position_blocked() -> None:
    provider = ExitBrokerRaises()

    guard = DuplicateOrderGuard()

    service = ExitExecutionService(
        provider=provider,
        duplicate_guard=guard,
        allow_live_exit_orders=True,
    )

    plan = make_exit_plan()

    result = service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.accepted is False

    assert (
        result.decision
        is ExitExecutionDecision.EXECUTION_FAILED
    )

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{plan.position_id.value}"
    )

    record = guard.get(
        key
    )

    assert record is not None

    assert (
        record.state
        is IdempotencyState.SUBMITTED
    )


def test_cancel_failure_blocks_force_exit_replacement() -> None:
    position = make_filled_position()

    guard = DuplicateOrderGuard()

    key, intent = make_active_exit_context(
        guard,
        position,
    )

    provider = ReconciliationBroker(
        first_status=BrokerOrderStatus.OPEN,
        cancel_success=False,
    )

    service = ExitReconciliationService(
        provider=provider,
        exit_plan_builder=(
            ExitPlanBuilder(
                TargetBookingPolicy()
            )
        ),
        duplicate_guard=guard,
    )

    result = service.reconcile_for_force_exit(
        position=position,
        active_exit_intent=intent,
        broker_reference=(
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="TARGET-T22",
            )
        ),
        requested_at=FORCE_TIME,
    )

    assert (
        result.decision
        is ExitReconciliationDecision.CANCELLATION_FAILED
    )

    assert result.force_exit_plan is None

    guard_record = guard.get(
        key
    )

    assert guard_record is not None

    assert (
        guard_record.state
        is IdempotencyState.SUBMITTED
    )


def test_unconfirmed_cancellation_blocks_replacement() -> None:
    position = make_filled_position()

    guard = DuplicateOrderGuard()

    key, intent = make_active_exit_context(
        guard,
        position,
    )

    provider = ReconciliationBroker(
        first_status=BrokerOrderStatus.OPEN,
        final_status=BrokerOrderStatus.OPEN,
        cancel_success=True,
    )

    service = ExitReconciliationService(
        provider=provider,
        exit_plan_builder=(
            ExitPlanBuilder(
                TargetBookingPolicy()
            )
        ),
        duplicate_guard=guard,
    )

    result = service.reconcile_for_force_exit(
        position=position,
        active_exit_intent=intent,
        broker_reference=(
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="TARGET-T22",
            )
        ),
        requested_at=FORCE_TIME,
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .CANCELLATION_NOT_CONFIRMED
    )

    assert result.force_exit_plan is None

    guard_record = guard.get(
        key
    )

    assert guard_record is not None

    assert (
        guard_record.state
        is IdempotencyState.SUBMITTED
    )


def test_target_fill_during_cancel_race_blocks_second_sell() -> None:
    position = make_filled_position()

    guard = DuplicateOrderGuard()

    key, intent = make_active_exit_context(
        guard,
        position,
    )

    provider = ReconciliationBroker(
        first_status=BrokerOrderStatus.OPEN,
        first_filled=0,
        final_status=BrokerOrderStatus.FILLED,
        final_filled=65,
        cancel_success=True,
    )

    service = ExitReconciliationService(
        provider=provider,
        exit_plan_builder=(
            ExitPlanBuilder(
                TargetBookingPolicy()
            )
        ),
        duplicate_guard=guard,
    )

    result = service.reconcile_for_force_exit(
        position=position,
        active_exit_intent=intent,
        broker_reference=(
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="TARGET-T22",
            )
        ),
        requested_at=FORCE_TIME,
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .POSITION_ALREADY_CLOSED
    )

    assert result.remaining_quantity == 0
    assert result.force_exit_plan is None

    guard_record = guard.get(
        key
    )

    assert guard_record is not None

    assert (
        guard_record.state
        is IdempotencyState.COMPLETED
    )


def test_partial_fill_replacement_uses_final_broker_quantity() -> None:
    position = make_filled_position(
        quantity=65
    )

    guard = DuplicateOrderGuard()

    key, intent = make_active_exit_context(
        guard,
        position,
    )

    provider = ReconciliationBroker(
        first_status=(
            BrokerOrderStatus.PARTIALLY_FILLED
        ),
        first_filled=20,
        final_status=(
            BrokerOrderStatus.CANCELLED
        ),
        final_filled=30,
        cancel_success=True,
    )

    service = ExitReconciliationService(
        provider=provider,
        exit_plan_builder=(
            ExitPlanBuilder(
                TargetBookingPolicy()
            )
        ),
        duplicate_guard=guard,
    )

    result = service.reconcile_for_force_exit(
        position=position,
        active_exit_intent=intent,
        broker_reference=(
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="TARGET-T22",
            )
        ),
        requested_at=FORCE_TIME,
    )

    assert (
        result.decision
        is ExitReconciliationDecision.FORCE_EXIT_READY
    )

    assert result.filled_quantity == 30
    assert result.remaining_quantity == 35

    assert result.force_exit_plan is not None

    assert (
        result.force_exit_plan.quantity
        == 35
    )

    guard_record = guard.get(
        key
    )

    assert guard_record is not None

    assert (
        guard_record.state
        is IdempotencyState.RELEASED
    )


def test_wrong_exit_intent_position_is_rejected() -> None:
    position = make_filled_position()

    wrong_intent = ExitOrderIntent(
        intent_id=ExitOrderIntentId(
            "EXIT-WRONG-T22"
        ),
        position_id=FilledPositionId(
            "POS-WRONG"
        ),
        security_id="41009",
        symbol="NIFTY",
        option_type=OptionType.CALL,
        transaction_type=(
            ExitTransactionType.SELL
        ),
        order_type=ExitOrderType.LIMIT,
        quantity=65,
        price=126,
        reason=ExitReason.TARGET,
        created_at=NOW,
    )

    provider = ReconciliationBroker()

    service = ExitReconciliationService(
        provider=provider,
        exit_plan_builder=(
            ExitPlanBuilder(
                TargetBookingPolicy()
            )
        ),
        duplicate_guard=DuplicateOrderGuard(),
    )

    result = service.reconcile_for_force_exit(
        position=position,
        active_exit_intent=wrong_intent,
        broker_reference=(
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="TARGET-T22",
            )
        ),
        requested_at=FORCE_TIME,
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .INVALID_EXIT_REFERENCE
    )

    assert provider.status_calls == 0
    assert provider.cancel_calls == 0


class ScopedReconciliationBroker(
    ExitExecutionProvider
):
    """
    Broker double whose exit-order quantity can be smaller
    than the historical FilledPosition quantity.
    """

    def __init__(
        self,
        *,
        order_quantity: int,
        first_status: BrokerOrderStatus,
        first_filled: int,
        final_status: BrokerOrderStatus,
        final_filled: int,
    ) -> None:
        self.order_quantity = (
            order_quantity
        )

        self.first_status = (
            first_status
        )

        self.first_filled = (
            first_filled
        )

        self.final_status = (
            final_status
        )

        self.final_filled = (
            final_filled
        )

        self.status_calls = 0
        self.cancel_calls = 0

    @property
    def broker_name(
        self,
    ) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent: ExitOrderIntent,
    ) -> ExitExecutionResult:
        raise NotImplementedError

    def cancel_exit(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> ExitCancellationResult:
        self.cancel_calls += 1

        return ExitCancellationResult(
            broker_reference=(
                broker_reference
            ),
            success=True,
            status=(
                BrokerOrderStatus.CANCELLED
            ),
            cancelled_at=FORCE_TIME,
        )

    def get_exit_status(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> ExitOrderSnapshot:
        self.status_calls += 1

        if self.status_calls == 1:
            status = self.first_status
            filled_quantity = (
                self.first_filled
            )

        else:
            status = self.final_status
            filled_quantity = (
                self.final_filled
            )

        return ExitOrderSnapshot(
            broker_reference=(
                broker_reference
            ),
            status=status,
            quantity=(
                self.order_quantity
            ),
            filled_quantity=(
                filled_quantity
            ),
            average_price=(
                126.0
                if filled_quantity > 0
                else None
            ),
            updated_at=FORCE_TIME,
        )


def test_force_exit_reconciliation_uses_active_sell_quantity_scope() -> None:
    """
    Original entry quantity can be larger than the currently
    active SELL.

    Example:

        original position = 65
        active SELL       = 35
        final SELL fill   = 15

    Replacement must be 20, never 50.
    """

    position = make_filled_position(
        quantity=65
    )

    guard = DuplicateOrderGuard()

    key, original_intent = (
        make_active_exit_context(
            guard,
            position,
        )
    )

    active_intent = ExitOrderIntent(
        intent_id=(
            original_intent.intent_id
        ),
        position_id=(
            original_intent.position_id
        ),
        security_id=(
            original_intent.security_id
        ),
        symbol=(
            original_intent.symbol
        ),
        option_type=(
            original_intent.option_type
        ),
        transaction_type=(
            original_intent
            .transaction_type
        ),
        order_type=(
            original_intent.order_type
        ),
        quantity=35,
        price=(
            original_intent.price
        ),
        reason=(
            original_intent.reason
        ),
        created_at=(
            original_intent.created_at
        ),
    )

    provider = (
        ScopedReconciliationBroker(
            order_quantity=35,
            first_status=(
                BrokerOrderStatus
                .PARTIALLY_FILLED
            ),
            first_filled=10,
            final_status=(
                BrokerOrderStatus.CANCELLED
            ),
            final_filled=15,
        )
    )

    service = ExitReconciliationService(
        provider=provider,
        exit_plan_builder=(
            ExitPlanBuilder(
                TargetBookingPolicy()
            )
        ),
        duplicate_guard=guard,
    )

    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="PARTIAL-SCOPE-EXIT",
    )

    result = (
        service.reconcile_for_force_exit(
            position=position,
            active_exit_intent=(
                active_intent
            ),
            broker_reference=reference,
            requested_at=FORCE_TIME,
        )
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .FORCE_EXIT_READY
    )

    assert result.original_quantity == 35

    assert result.filled_quantity == 15

    assert result.remaining_quantity == 20

    assert result.force_exit_plan is not None

    assert (
        result.force_exit_plan.quantity
        == 20
    )

    assert provider.cancel_calls == 1
    assert provider.status_calls == 2

    guard_record = guard.get(
        key
    )

    assert guard_record is not None

    assert (
        guard_record.state
        is IdempotencyState.RELEASED
    )


def test_force_exit_reconciliation_rejects_broker_quantity_mismatch() -> None:
    """
    Broker order truth must describe the same quantity as the
    active SELL intent.

    Phoenix must fail closed before cancellation or replacement
    when those identities disagree.
    """

    position = make_filled_position(
        quantity=65
    )

    guard = DuplicateOrderGuard()

    key, original_intent = (
        make_active_exit_context(
            guard,
            position,
        )
    )

    active_intent = ExitOrderIntent(
        intent_id=(
            original_intent.intent_id
        ),
        position_id=(
            original_intent.position_id
        ),
        security_id=(
            original_intent.security_id
        ),
        symbol=(
            original_intent.symbol
        ),
        option_type=(
            original_intent.option_type
        ),
        transaction_type=(
            original_intent
            .transaction_type
        ),
        order_type=(
            original_intent.order_type
        ),
        quantity=35,
        price=(
            original_intent.price
        ),
        reason=(
            original_intent.reason
        ),
        created_at=(
            original_intent.created_at
        ),
    )

    provider = (
        ScopedReconciliationBroker(
            # Deliberate broker mismatch.
            order_quantity=65,
            first_status=(
                BrokerOrderStatus.OPEN
            ),
            first_filled=0,
            final_status=(
                BrokerOrderStatus.CANCELLED
            ),
            final_filled=0,
        )
    )

    service = ExitReconciliationService(
        provider=provider,
        exit_plan_builder=(
            ExitPlanBuilder(
                TargetBookingPolicy()
            )
        ),
        duplicate_guard=guard,
    )

    result = (
        service.reconcile_for_force_exit(
            position=position,
            active_exit_intent=(
                active_intent
            ),
            broker_reference=(
                BrokerOrderReference(
                    broker_name="FAKE",
                    order_id=(
                        "WRONG-QUANTITY-EXIT"
                    ),
                )
            ),
            requested_at=FORCE_TIME,
        )
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .INVALID_EXIT_REFERENCE
    )

    assert result.original_quantity == 35
    assert result.filled_quantity == 0
    assert result.remaining_quantity == 35

    assert result.force_exit_plan is None

    # Fail closed BEFORE cancellation.
    assert provider.status_calls == 1
    assert provider.cancel_calls == 0

    guard_record = guard.get(
        key
    )

    assert guard_record is not None

    assert (
        guard_record.state
        is IdempotencyState.SUBMITTED
    )
