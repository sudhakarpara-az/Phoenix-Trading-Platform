from datetime import date, datetime

from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
)
from src.execution.dry_run_executor import (
    DryRunExecutor,
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
    OrderPricingPolicy,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
)
from src.execution.quantity_policy import (
    QuantityPolicy,
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
from src.strategy.strategy_types import EntryLevel


TRADING_DATE = date(2026, 8, 7)
EXPIRY = date(2026, 8, 11)

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


class CountingBroker(
    BrokerExecutionProvider
):
    def __init__(self) -> None:
        self.submit_count = 0

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_order(
        self,
        intent,
    ) -> ExecutionResult:
        self.submit_count += 1

        return ExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=(
                BrokerOrderReference(
                    broker_name="FAKE",
                    order_id="ORDER-001",
                )
            ),
            submitted_at=NOW,
        )

    def cancel_order(
        self,
        broker_reference,
    ) -> BrokerCancellationResult:
        return BrokerCancellationResult(
            broker_reference=broker_reference,
            success=True,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=NOW,
        )

    def get_order_status(
        self,
        broker_reference,
    ) -> BrokerOrderSnapshot:
        return BrokerOrderSnapshot(
            broker_reference=broker_reference,
            status=BrokerOrderStatus.OPEN,
            quantity=65,
            filled_quantity=0,
            average_price=None,
            updated_at=NOW,
        )


def make_signal(
    signal_id: str,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            signal_id
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )


def make_option() -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol="NIFTY50-20260811-24450-CE",
                security_id="41009",
                option_type=OptionType.CALL,
                strike=24450.0,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=205.0,
                bid=204.4,
                ask=204.9,
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


def make_service(
    *,
    allow_live_orders: bool = False,
):
    broker = CountingBroker()

    guard = DuplicateOrderGuard()

    dry_run = DryRunExecutor()

    state_machine = OrderStateMachine()

    service = ExecutionService(
        pricing_policy=OrderPricingPolicy(),
        quantity_policy=QuantityPolicy(),
        eligibility_validator=(
            OrderEligibilityValidator()
        ),
        state_machine=state_machine,
        broker_provider=broker,
        idempotency_guard=guard,
        dry_run_executor=dry_run,
        allow_live_orders=allow_live_orders,
    )

    return (
        service,
        broker,
        guard,
        dry_run,
        state_machine,
    )


def test_same_signal_creates_only_one_dry_run_order() -> None:
    (
        service,
        broker,
        _,
        dry_run,
        _,
    ) = make_service()

    signal = make_signal(
        "SIG-SAME"
    )

    first = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    second = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert first.accepted is True
    assert first.submitted is True

    assert second.accepted is False
    assert second.intent is None

    assert (
        second.eligibility.reason
        is OrderEligibilityReason.DUPLICATE_ORDER
    )

    assert dry_run.count() == 1

    assert broker.submit_count == 0


def test_different_signals_can_execute() -> None:
    (
        service,
        _,
        _,
        dry_run,
        _,
    ) = make_service()

    first = service.execute(
        signal=make_signal(
            "SIG-001"
        ),
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    second = service.execute(
        signal=make_signal(
            "SIG-002"
        ),
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert first.accepted is True
    assert second.accepted is True

    assert dry_run.count() == 2


def test_completed_dry_run_blocks_signal_replay() -> None:
    (
        service,
        _,
        guard,
        _,
        _,
    ) = make_service()

    signal = make_signal(
        "SIG-001"
    )

    service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    record = guard.get(
        key
    )

    assert record is not None

    assert (
        record.state
        is IdempotencyState.COMPLETED
    )


def test_invalid_quantity_releases_reservation() -> None:
    (
        service,
        _,
        guard,
        _,
        _,
    ) = make_service()

    signal = make_signal(
        "SIG-INVALID-QTY"
    )

    result = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=100,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.accepted is False

    assert (
        result.eligibility.reason
        is OrderEligibilityReason.INVALID_QUANTITY
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert guard.is_blocked(
        key
    ) is False


def test_eligibility_rejection_releases_reservation() -> None:
    (
        service,
        _,
        guard,
        _,
        state_machine,
    ) = make_service()

    signal = make_signal(
        "SIG-DISABLED"
    )

    result = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(
            trading_enabled=False
        ),
    )

    assert result.accepted is False

    assert result.intent is not None

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.REJECTED
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert guard.is_blocked(
        key
    ) is False


def test_live_gate_blocks_without_broker_call() -> None:
    (
        service,
        broker,
        guard,
        _,
        state_machine,
    ) = make_service(
        allow_live_orders=False
    )

    signal = make_signal(
        "SIG-LIVE-BLOCK"
    )

    result = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.accepted is False

    assert (
        result.eligibility.reason
        is OrderEligibilityReason.LIVE_EXECUTION_DISABLED
    )

    assert broker.submit_count == 0

    assert result.intent is not None

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.CANCELLED
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert guard.is_blocked(
        key
    ) is False


def test_live_enabled_calls_broker_once_for_duplicate_signal() -> None:
    (
        service,
        broker,
        guard,
        _,
        _,
    ) = make_service(
        allow_live_orders=True
    )

    signal = make_signal(
        "SIG-LIVE"
    )

    first = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    second = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert first.submitted is True

    assert second.accepted is False

    assert (
        second.eligibility.reason
        is OrderEligibilityReason.DUPLICATE_ORDER
    )

    assert broker.submit_count == 1

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert guard.is_blocked(
        key
    ) is True