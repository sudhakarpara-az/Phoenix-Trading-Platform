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
    OrderPricingConfig,
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
from src.strategy.strategy_types import (
    EntryLevel,
)


TRADING_DATE = date(2026, 8, 7)
EXPIRY = date(2026, 8, 11)

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


class FakeBroker(
    BrokerExecutionProvider
):
    """
    Broker fake used only to prove that DRY_RUN never
    reaches broker submission.
    """

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
                    order_id="FAKE-001",
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
    *,
    signal_id: str = "SIG-M05-M06-001",
    direction: SignalDirection = SignalDirection.CALL,
    level: EntryLevel = EntryLevel.K5,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            signal_id
        ),
        trading_date=TRADING_DATE,
        level=level,
        direction=direction,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )


def make_selected_option(
    *,
    option_type: OptionType = OptionType.CALL,
    security_id: str = "41009",
    strike: float = 24450.0,
    ltp: float = 205.0,
    delta: float = 0.64,
    lot_size: int = 65,
) -> SelectedOption:
    side = (
        "CE"
        if option_type is OptionType.CALL
        else "PE"
    )

    candidate = OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol=(
                "NIFTY50-20260811-"
                f"{int(strike)}-{side}"
            ),
            security_id=security_id,
            option_type=option_type,
            strike=strike,
            expiry=EXPIRY,
            lot_size=lot_size,
        ),
        quote=OptionQuote(
            ltp=ltp,
            bid=ltp - 0.50,
            ask=ltp + 0.25,
            volume=10000,
            open_interest=50000,
            received_at=NOW,
        ),
        greeks=OptionGreeks(
            delta=delta,
            gamma=0.001,
            theta=-4.0,
            vega=6.0,
            implied_volatility=12.0,
            calculated_at=NOW,
        ),
    )

    return SelectedOption(
        candidate=candidate,
        selected_at=NOW,
        selection_delta_target=0.64,
    )


def make_service(
    *,
    buffer: float = 1.0,
):
    broker = FakeBroker()

    state_machine = OrderStateMachine()

    guard = DuplicateOrderGuard()

    dry_run = DryRunExecutor()

    service = ExecutionService(
        pricing_policy=OrderPricingPolicy(
            OrderPricingConfig(
                entry_buffer_points=buffer,
                tick_size=0.05,
            )
        ),
        quantity_policy=QuantityPolicy(),
        eligibility_validator=(
            OrderEligibilityValidator()
        ),
        state_machine=state_machine,
        broker_provider=broker,
        idempotency_guard=guard,
        dry_run_executor=dry_run,
        allow_live_orders=False,
    )

    return (
        service,
        broker,
        state_machine,
        guard,
        dry_run,
    )


def test_m05_selected_call_becomes_m06_order_intent() -> None:
    (
        service,
        broker,
        state_machine,
        guard,
        dry_run,
    ) = make_service()

    signal = make_signal(
        direction=SignalDirection.CALL
    )

    selected_option = make_selected_option(
        option_type=OptionType.CALL,
        security_id="41009",
        strike=24450,
        ltp=205.0,
        delta=0.66844,
    )

    result = service.execute(
        signal=signal,
        selected_option=selected_option,
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.accepted is True
    assert result.submitted is True

    assert result.intent is not None

    assert (
        result.intent.selected_option.security_id
        == "41009"
    )

    assert result.intent.quantity == 65

    assert (
        result.intent.limit_price
        == 206.0
    )

    assert broker.submit_count == 0

    assert dry_run.count() == 1

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.OPEN
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


def test_m05_selected_put_becomes_m06_order_intent() -> None:
    (
        service,
        broker,
        _,
        _,
        dry_run,
    ) = make_service()

    signal = make_signal(
        signal_id="SIG-M05-M06-PUT",
        direction=SignalDirection.PUT,
    )

    selected_option = make_selected_option(
        option_type=OptionType.PUT,
        security_id="41019",
        strike=24650,
        ltp=132.75,
        delta=-0.60225,
    )

    result = service.execute(
        signal=signal,
        selected_option=selected_option,
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.accepted is True

    assert result.intent is not None

    assert (
        result.intent.selected_option.option_type
        is OptionType.PUT
    )

    assert (
        result.intent.selected_option.security_id
        == "41019"
    )

    assert (
        result.intent.limit_price
        == 133.75
    )

    assert broker.submit_count == 0
    assert dry_run.count() == 1


def test_two_point_buffer_flows_through_integration() -> None:
    (
        service,
        _,
        _,
        _,
        _,
    ) = make_service(
        buffer=2.0
    )

    result = service.execute(
        signal=make_signal(
            signal_id="SIG-BUFFER-2"
        ),
        selected_option=make_selected_option(
            ltp=205.0
        ),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.pricing is not None

    assert (
        result.pricing.buffer_points
        == 2.0
    )

    assert (
        result.pricing.limit_price
        == 207.0
    )


def test_m05_lot_size_controls_m06_quantity_validation() -> None:
    (
        service,
        broker,
        state_machine,
        guard,
        dry_run,
    ) = make_service()

    signal = make_signal(
        signal_id="SIG-LOT-VALIDATION"
    )

    option = make_selected_option(
        lot_size=65
    )

    result = service.execute(
        signal=signal,
        selected_option=option,
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

    assert result.intent is None

    assert broker.submit_count == 0
    assert dry_run.count() == 0
    assert state_machine.count() == 0

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert guard.is_blocked(
        key
    ) is False


def test_two_lots_flow_from_m05_to_m06() -> None:
    (
        service,
        _,
        _,
        _,
        dry_run,
    ) = make_service()

    result = service.execute(
        signal=make_signal(
            signal_id="SIG-TWO-LOTS"
        ),
        selected_option=make_selected_option(
            lot_size=65
        ),
        quantity=130,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.accepted is True

    assert result.intent is not None

    assert result.intent.quantity == 130

    assert dry_run.count() == 1

    assert (
        dry_run.records()[0].quantity
        == 130
    )


def test_same_m05_signal_cannot_create_duplicate_m06_order() -> None:
    (
        service,
        broker,
        _,
        _,
        dry_run,
    ) = make_service()

    signal = make_signal(
        signal_id="SIG-DUPLICATE"
    )

    option = make_selected_option()

    first = service.execute(
        signal=signal,
        selected_option=option,
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    second = service.execute(
        signal=signal,
        selected_option=option,
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert first.accepted is True

    assert second.accepted is False

    assert (
        second.eligibility.reason
        is OrderEligibilityReason.DUPLICATE_ORDER
    )

    assert second.intent is None

    assert dry_run.count() == 1
    assert broker.submit_count == 0


def test_new_reentry_signal_is_allowed() -> None:
    (
        service,
        _,
        _,
        _,
        dry_run,
    ) = make_service()

    option = make_selected_option()

    first = service.execute(
        signal=make_signal(
            signal_id="SIG-K5-FIRST",
            level=EntryLevel.K5,
        ),
        selected_option=option,
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    reentry = service.execute(
        signal=make_signal(
            signal_id="SIG-K5-REENTRY",
            level=EntryLevel.K5,
        ),
        selected_option=option,
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert first.accepted is True
    assert reentry.accepted is True

    assert dry_run.count() == 2


def test_trading_disabled_blocks_m05_option_execution() -> None:
    (
        service,
        broker,
        state_machine,
        guard,
        dry_run,
    ) = make_service()

    signal = make_signal(
        signal_id="SIG-TRADING-DISABLED"
    )

    result = service.execute(
        signal=signal,
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(
            trading_enabled=False
        ),
    )

    assert result.accepted is False

    assert (
        result.eligibility.reason
        is OrderEligibilityReason.TRADING_DISABLED
    )

    assert broker.submit_count == 0
    assert dry_run.count() == 0

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


def test_platform_halt_blocks_execution() -> None:
    (
        service,
        broker,
        _,
        _,
        dry_run,
    ) = make_service()

    result = service.execute(
        signal=make_signal(
            signal_id="SIG-HALTED"
        ),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(
            platform_halted=True
        ),
    )

    assert result.accepted is False

    assert (
        result.eligibility.reason
        is OrderEligibilityReason.PLATFORM_HALTED
    )

    assert broker.submit_count == 0
    assert dry_run.count() == 0


def test_dry_run_never_calls_broker() -> None:
    (
        service,
        broker,
        _,
        _,
        dry_run,
    ) = make_service()

    result = service.execute(
        signal=make_signal(
            signal_id="SIG-NO-BROKER"
        ),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.submitted is True

    assert broker.submit_count == 0
    assert dry_run.count() == 1

    assert result.execution_result is not None

    assert (
        result.execution_result
        .broker_reference
        is not None
    )

    assert (
        result.execution_result
        .broker_reference
        .broker_name
        == "DRY_RUN"
    )