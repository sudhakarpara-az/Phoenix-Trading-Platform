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


def make_signal() -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-M06-T08"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500,
        level_price=24500,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )


def make_selected_option(
    *,
    ltp: float = 205.0,
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
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=ltp,
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


class FakeBrokerProvider(
    BrokerExecutionProvider
):
    def __init__(
        self,
        *,
        status: BrokerOrderStatus = (
            BrokerOrderStatus.OPEN
        ),
        success: bool = True,
    ) -> None:
        self._status = status
        self._success = success

        self.submit_count = 0
        self.last_intent = None

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_order(
        self,
        intent,
    ) -> ExecutionResult:
        self.submit_count += 1
        self.last_intent = intent

        reference = (
            BrokerOrderReference(
                broker_name="FAKE",
                order_id="FAKE-001",
            )
            if self._success
            else None
        )

        return ExecutionResult(
            intent_id=intent.intent_id,
            success=self._success,
            status=self._status,
            broker_reference=reference,
            submitted_at=intent.created_at,
            message=(
                None
                if self._success
                else "simulated broker failure"
            ),
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
            status=self._status,
            quantity=65,
            filled_quantity=0,
            average_price=None,
            updated_at=NOW,
        )


def make_service(
    *,
    provider=None,
    allow_live_orders: bool = False,
    buffer: float = 1.0,
):
    broker = (
        provider
        or FakeBrokerProvider()
    )

    state_machine = OrderStateMachine()

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
        allow_live_orders=allow_live_orders,
    )

    return (
        service,
        broker,
        state_machine,
    )


def test_dry_run_builds_order_intent() -> None:
    service, _, _ = make_service()

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.intent is not None

    assert result.intent.quantity == 65

    assert (
        result.intent.limit_price
        == 206.0
    )


def test_dry_run_uses_one_point_buffer() -> None:
    service, _, _ = make_service(
        buffer=1.0
    )

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(
            ltp=205.0
        ),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.pricing is not None

    assert result.pricing.reference_ltp == 205.0
    assert result.pricing.limit_price == 206.0


def test_dry_run_does_not_call_broker() -> None:
    service, broker, _ = make_service()

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.submitted is True

    assert broker.submit_count == 0


def test_dry_run_reference_is_marked_dry_run() -> None:
    service, _, _ = make_service()

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.execution_result is not None

    reference = (
        result.execution_result
        .broker_reference
    )

    assert reference is not None
    assert reference.broker_name == "DRY_RUN"


def test_dry_run_lifecycle_reaches_open() -> None:
    service, _, state_machine = make_service()

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.intent is not None

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.OPEN
    )


def test_invalid_quantity_is_rejected_before_intent_creation() -> None:
    service, broker, state_machine = (
        make_service()
    )

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
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
    assert state_machine.count() == 0


def test_trading_disabled_rejects_order() -> None:
    service, broker, state_machine = (
        make_service()
    )

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
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
        result.eligibility.reason
        is OrderEligibilityReason.TRADING_DISABLED
    )

    assert broker.submit_count == 0

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.REJECTED
    )


def test_platform_halt_rejects_order() -> None:
    service, broker, _ = make_service()

    result = service.execute(
        signal=make_signal(),
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


def test_live_mode_is_blocked_by_default() -> None:
    service, broker, state_machine = (
        make_service(
            allow_live_orders=False
        )
    )

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.accepted is False

    assert result.execution_result is None

    assert broker.submit_count == 0

    assert result.intent is not None

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.CANCELLED
    )


def test_live_enabled_routes_to_provider() -> None:
    broker = FakeBrokerProvider(
        status=BrokerOrderStatus.OPEN,
        success=True,
    )

    service, broker, state_machine = (
        make_service(
            provider=broker,
            allow_live_orders=True,
        )
    )

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert broker.submit_count == 1

    assert result.execution_result is not None
    assert result.execution_result.success is True

    assert result.intent is not None

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.OPEN
    )


def test_broker_filled_maps_to_filled_state() -> None:
    broker = FakeBrokerProvider(
        status=BrokerOrderStatus.FILLED,
        success=True,
    )

    service, _, state_machine = (
        make_service(
            provider=broker,
            allow_live_orders=True,
        )
    )

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.intent is not None

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.FILLED
    )


def test_broker_rejection_maps_to_rejected_state() -> None:
    broker = FakeBrokerProvider(
        status=BrokerOrderStatus.REJECTED,
        success=False,
    )

    service, _, state_machine = (
        make_service(
            provider=broker,
            allow_live_orders=True,
        )
    )

    result = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.intent is not None

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.REJECTED
    )


def test_intent_ids_are_unique() -> None:
    service, _, _ = make_service()

    first = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    second = service.execute(
        signal=make_signal(),
        selected_option=make_selected_option(),
        quantity=65,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert first.intent is not None
    assert second.intent is not None

    assert (
        first.intent.intent_id.value
        != second.intent.intent_id.value
    )