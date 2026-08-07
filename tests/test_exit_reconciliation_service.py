from datetime import date, datetime

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    OrderIntentId,
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
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
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
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


NOW = datetime(
    2026,
    8,
    7,
    15,
    15,
)

EXPIRY = date(
    2026,
    8,
    11,
)


def make_option() -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-24450-CE"
                ),
                security_id="41009",
                option_type=OptionType.CALL,
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=126,
                bid=125.95,
                ask=126.05,
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


def make_position(
    *,
    quantity: int = 65,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-T20"
        ),
        signal_id=SignalId(
            "SIG-T20"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-T20"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-T20",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=100,
        filled_at=NOW,
    )


def make_exit_intent(
    *,
    quantity: int = 65,
) -> ExitOrderIntent:
    return ExitOrderIntent(
        intent_id=ExitOrderIntentId(
            "EXIT-T20"
        ),
        position_id=FilledPositionId(
            "POS-T20"
        ),
        security_id="41009",
        symbol=(
            "NIFTY50-20260811-24450-CE"
        ),
        option_type=OptionType.CALL,
        transaction_type=(
            ExitTransactionType.SELL
        ),
        order_type=ExitOrderType.LIMIT,
        quantity=quantity,
        price=126,
        reason=ExitReason.TARGET,
        created_at=NOW,
    )


class FakeReconciliationProvider(
    ExitExecutionProvider
):
    def __init__(
        self,
        *,
        initial_status=BrokerOrderStatus.OPEN,
        initial_filled=0,
        final_status=BrokerOrderStatus.CANCELLED,
        final_filled=0,
        cancellation_success=True,
    ) -> None:
        self.initial_status = initial_status
        self.initial_filled = initial_filled

        self.final_status = final_status
        self.final_filled = final_filled

        self.cancellation_success = (
            cancellation_success
        )

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
            "reconciliation must not submit exit"
        )

    def cancel_exit(
        self,
        broker_reference,
    ) -> ExitCancellationResult:
        self.cancel_calls += 1

        return ExitCancellationResult(
            broker_reference=broker_reference,
            success=self.cancellation_success,
            status=(
                BrokerOrderStatus.CANCELLED
                if self.cancellation_success
                else BrokerOrderStatus.OPEN
            ),
            cancelled_at=NOW,
            message=(
                None
                if self.cancellation_success
                else "cancel failed"
            ),
        )

    def get_exit_status(
        self,
        broker_reference,
    ) -> ExitOrderSnapshot:
        self.status_calls += 1

        if self.status_calls == 1:
            status = self.initial_status
            filled = self.initial_filled
        else:
            status = self.final_status
            filled = self.final_filled

        average_price = (
            126.0
            if filled > 0
            else None
        )

        return ExitOrderSnapshot(
            broker_reference=broker_reference,
            status=status,
            quantity=65,
            filled_quantity=filled,
            average_price=average_price,
            updated_at=NOW,
        )


def prepare_guard(
    guard: DuplicateOrderGuard,
    position: FilledPosition,
) -> IdempotencyKey:
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
        intent_id="EXIT-T20",
        changed_at=NOW,
    )

    guard.mark_submitted(
        key=key,
        changed_at=NOW,
    )

    return key


def make_service(
    provider,
    guard,
):
    return ExitReconciliationService(
        provider=provider,
        exit_plan_builder=(
            ExitPlanBuilder(
                TargetBookingPolicy()
            )
        ),
        duplicate_guard=guard,
    )


REFERENCE = BrokerOrderReference(
    broker_name="FAKE",
    order_id="EXIT-BROKER-001",
)


def test_open_target_is_cancelled_before_force_exit() -> None:
    position = make_position()

    guard = DuplicateOrderGuard()

    key = prepare_guard(
        guard,
        position,
    )

    provider = FakeReconciliationProvider(
        initial_status=BrokerOrderStatus.OPEN,
        final_status=BrokerOrderStatus.CANCELLED,
    )

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=make_exit_intent(),
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert (
        result.decision
        is ExitReconciliationDecision.FORCE_EXIT_READY
    )

    assert provider.cancel_calls == 1

    assert result.remaining_quantity == 65

    assert result.force_exit_plan is not None

    assert (
        result.force_exit_plan.order_type
        is ExitOrderType.MARKET
    )

    assert (
        result.force_exit_plan.reason
        is ExitReason.FORCE_EXIT
    )

    assert (
        guard.get(key).state
        is IdempotencyState.RELEASED
    )


def test_partial_fill_force_exits_only_remaining_quantity() -> None:
    position = make_position(
        quantity=65
    )

    guard = DuplicateOrderGuard()

    prepare_guard(
        guard,
        position,
    )

    provider = FakeReconciliationProvider(
        initial_status=(
            BrokerOrderStatus.PARTIALLY_FILLED
        ),
        initial_filled=20,
        final_status=(
            BrokerOrderStatus.CANCELLED
        ),
        final_filled=30,
    )

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=make_exit_intent(),
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert result.filled_quantity == 30

    assert result.remaining_quantity == 35

    assert result.force_exit_plan is not None

    assert (
        result.force_exit_plan.quantity
        == 35
    )


def test_final_status_query_protects_cancel_fill_race() -> None:
    position = make_position()

    guard = DuplicateOrderGuard()

    key = prepare_guard(
        guard,
        position,
    )

    provider = FakeReconciliationProvider(
        initial_status=BrokerOrderStatus.OPEN,
        initial_filled=0,
        final_status=BrokerOrderStatus.FILLED,
        final_filled=65,
    )

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=make_exit_intent(),
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .POSITION_ALREADY_CLOSED
    )

    assert result.remaining_quantity == 0

    assert result.force_exit_plan is None

    assert (
        guard.get(key).state
        is IdempotencyState.COMPLETED
    )


def test_already_filled_exit_sends_no_cancel() -> None:
    position = make_position()

    guard = DuplicateOrderGuard()

    prepare_guard(
        guard,
        position,
    )

    provider = FakeReconciliationProvider(
        initial_status=BrokerOrderStatus.FILLED,
        initial_filled=65,
    )

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=make_exit_intent(),
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .POSITION_ALREADY_CLOSED
    )

    assert provider.cancel_calls == 0

    assert result.force_exit_required is False


def test_cancel_failure_blocks_market_replacement() -> None:
    position = make_position()

    guard = DuplicateOrderGuard()

    key = prepare_guard(
        guard,
        position,
    )

    provider = FakeReconciliationProvider(
        initial_status=BrokerOrderStatus.OPEN,
        cancellation_success=False,
    )

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=make_exit_intent(),
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .CANCELLATION_FAILED
    )

    assert result.force_exit_plan is None

    assert (
        guard.get(key).state
        is IdempotencyState.SUBMITTED
    )


def test_unconfirmed_cancel_blocks_market_replacement() -> None:
    position = make_position()

    guard = DuplicateOrderGuard()

    key = prepare_guard(
        guard,
        position,
    )

    provider = FakeReconciliationProvider(
        initial_status=BrokerOrderStatus.OPEN,
        final_status=BrokerOrderStatus.OPEN,
    )

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=make_exit_intent(),
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .CANCELLATION_NOT_CONFIRMED
    )

    assert result.force_exit_plan is None

    assert (
        guard.get(key).state
        is IdempotencyState.SUBMITTED
    )


def test_cancelled_exit_can_be_replaced() -> None:
    position = make_position()

    guard = DuplicateOrderGuard()

    prepare_guard(
        guard,
        position,
    )

    provider = FakeReconciliationProvider(
        initial_status=BrokerOrderStatus.CANCELLED,
        initial_filled=10,
    )

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=make_exit_intent(),
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert (
        result.decision
        is ExitReconciliationDecision.FORCE_EXIT_READY
    )

    assert result.remaining_quantity == 55

    assert provider.cancel_calls == 0

    assert result.force_exit_plan is not None

    assert (
        result.force_exit_plan.quantity
        == 55
    )


def test_wrong_position_exit_intent_is_blocked() -> None:
    position = make_position()

    wrong_intent = ExitOrderIntent(
        intent_id=ExitOrderIntentId(
            "EXIT-WRONG"
        ),
        position_id=FilledPositionId(
            "POS-OTHER"
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

    guard = DuplicateOrderGuard()

    provider = FakeReconciliationProvider()

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=wrong_intent,
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert (
        result.decision
        is ExitReconciliationDecision
        .INVALID_EXIT_REFERENCE
    )

    assert provider.status_calls == 0
    assert provider.cancel_calls == 0


def test_force_exit_plan_is_market_order() -> None:
    position = make_position()

    guard = DuplicateOrderGuard()

    prepare_guard(
        guard,
        position,
    )

    provider = FakeReconciliationProvider()

    result = make_service(
        provider,
        guard,
    ).reconcile_for_force_exit(
        position=position,
        active_exit_intent=make_exit_intent(),
        broker_reference=REFERENCE,
        requested_at=NOW,
    )

    assert result.force_exit_plan is not None

    assert (
        result.force_exit_plan.order_type
        is ExitOrderType.MARKET
    )

    assert (
        result.force_exit_plan.exit_price
        is None
    )