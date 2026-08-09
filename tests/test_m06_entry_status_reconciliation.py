from datetime import (
    date,
    datetime,
    timedelta,
)

import pytest

from src.execution.broker_execution_provider import (
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
from src.execution.idempotency_guard import (
    IdempotencyKey,
    IdempotencyState,
)
from src.execution.order_eligibility_validator import (
    OrderEligibilityContext,
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
    10,
    0,
)

REFERENCE = BrokerOrderReference(
    broker_name="DHAN",
    order_id="ENTRY-T14-001",
)


def make_signal() -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-T14-ENTRY-RECON"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        instrument_security_id="41009",
        instrument_symbol=(
            "NIFTY50-20260811-24450-CE"
        ),
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=100.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
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
                strike=24450.0,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=100.0,
                bid=99.95,
                ask=100.05,
                volume=10000,
                open_interest=50000,
                received_at=NOW,
            ),
            greeks=OptionGreeks(
                delta=0.60,
                calculated_at=NOW,
            ),
        ),
        selected_at=NOW,
        selection_delta_target=0.60,
    )


class FakeEntryBroker:
    def __init__(self) -> None:
        self.current_status = (
            BrokerOrderStatus.OPEN
        )
        self.filled_quantity = 0
        self.average_price = None
        self.reference = REFERENCE
        self.status_calls = 0

    @property
    def broker_name(self) -> str:
        return "DHAN"

    def submit_order(
        self,
        intent,
    ) -> ExecutionResult:
        return ExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=self.reference,
            submitted_at=NOW,
        )

    def cancel_order(
        self,
        broker_reference,
    ):
        raise AssertionError(
            "cancel_order must not be called"
        )

    def get_order_status(
        self,
        broker_reference,
    ) -> BrokerOrderSnapshot:
        self.status_calls += 1

        return BrokerOrderSnapshot(
            broker_reference=self.reference,
            status=self.current_status,
            quantity=65,
            filled_quantity=(
                self.filled_quantity
            ),
            average_price=(
                self.average_price
            ),
            updated_at=(
                NOW
                + timedelta(seconds=1)
            ),
        )


def make_service():
    broker = FakeEntryBroker()
    state_machine = OrderStateMachine()

    service = ExecutionService(
        pricing_policy=(
            OrderPricingPolicy()
        ),
        quantity_policy=(
            QuantityPolicy()
        ),
        eligibility_validator=(
            OrderEligibilityValidator()
        ),
        state_machine=state_machine,
        broker_provider=broker,
        allow_live_orders=True,
    )

    return (
        service,
        broker,
        state_machine,
    )


def execute_open_entry(
    service: ExecutionService,
):
    signal = make_signal()

    result = service.execute(
        signal=signal,
        selected_option=make_option(),
        quantity=65,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
        context=OrderEligibilityContext(),
    )

    assert result.intent is not None
    assert result.execution_result is not None

    return (
        signal,
        result,
    )


def test_refresh_uses_exact_owned_broker_provider() -> None:
    service, broker, _ = make_service()

    assert (
        service.broker_provider
        is broker
    )


def test_open_entry_can_reconcile_to_filled() -> None:
    (
        service,
        broker,
        state_machine,
    ) = make_service()

    signal, result = execute_open_entry(
        service
    )

    broker.current_status = (
        BrokerOrderStatus.FILLED
    )
    broker.filled_quantity = 65
    broker.average_price = 100.65

    snapshot = (
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=(
                result.execution_result
            ),
        )
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.FILLED
    )

    assert (
        snapshot.average_price
        == 100.65
    )

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.FILLED
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert (
        service.idempotency_guard
        .get(key)
        .state
        is IdempotencyState.COMPLETED
    )


def test_unknown_status_moves_to_reconciliation_required() -> None:
    (
        service,
        broker,
        state_machine,
    ) = make_service()

    signal, result = execute_open_entry(
        service
    )

    broker.current_status = (
        BrokerOrderStatus.UNKNOWN
    )

    snapshot = (
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=(
                result.execution_result
            ),
        )
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.UNKNOWN
    )

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState
        .RECONCILIATION_REQUIRED
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert (
        service.idempotency_guard
        .get(key)
        .state
        is IdempotencyState.SUBMITTED
    )


def test_reconciliation_required_can_later_become_filled() -> None:
    (
        service,
        broker,
        state_machine,
    ) = make_service()

    signal, result = execute_open_entry(
        service
    )

    broker.current_status = (
        BrokerOrderStatus.UNKNOWN
    )

    service.refresh_entry_order_status(
        intent=result.intent,
        execution_result=(
            result.execution_result
        ),
    )

    broker.current_status = (
        BrokerOrderStatus.FILLED
    )
    broker.filled_quantity = 65
    broker.average_price = 100.70

    snapshot = (
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=(
                result.execution_result
            ),
        )
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.FILLED
    )

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.FILLED
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert (
        service.idempotency_guard
        .get(key)
        .state
        is IdempotencyState.COMPLETED
    )


def test_proven_cancel_releases_submitted_idempotency() -> None:
    service, broker, _ = make_service()

    signal, result = execute_open_entry(
        service
    )

    broker.current_status = (
        BrokerOrderStatus.CANCELLED
    )

    service.refresh_entry_order_status(
        intent=result.intent,
        execution_result=(
            result.execution_result
        ),
    )

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert (
        service.idempotency_guard
        .get(key)
        .state
        is IdempotencyState.RELEASED
    )


def test_same_open_status_refresh_is_idempotent() -> None:
    (
        service,
        _,
        state_machine,
    ) = make_service()

    _, result = execute_open_entry(
        service
    )

    snapshot = (
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=(
                result.execution_result
            ),
        )
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.OPEN
    )

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.OPEN
    )


def test_wrong_execution_intent_is_rejected_before_broker_query() -> None:
    service, broker, _ = make_service()

    _, result = execute_open_entry(
        service
    )

    wrong = ExecutionResult(
        intent_id=(
            result.intent.intent_id.__class__(
                "WRONG-INTENT"
            )
        ),
        success=True,
        status=BrokerOrderStatus.OPEN,
        broker_reference=REFERENCE,
        submitted_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "execution result does not belong"
        ),
    ):
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=wrong,
        )

    assert broker.status_calls == 0


def test_broker_quantity_mismatch_fails_closed() -> None:
    class WrongQuantityBroker(
        FakeEntryBroker
    ):
        def get_order_status(
            self,
            broker_reference,
        ) -> BrokerOrderSnapshot:
            return BrokerOrderSnapshot(
                broker_reference=self.reference,
                status=BrokerOrderStatus.FILLED,
                quantity=130,
                filled_quantity=130,
                average_price=100.65,
                updated_at=(
                    NOW
                    + timedelta(seconds=1)
                ),
            )

    broker = WrongQuantityBroker()
    state_machine = OrderStateMachine()

    service = ExecutionService(
        pricing_policy=OrderPricingPolicy(),
        quantity_policy=QuantityPolicy(),
        eligibility_validator=(
            OrderEligibilityValidator()
        ),
        state_machine=state_machine,
        broker_provider=broker,
        allow_live_orders=True,
    )

    _, result = execute_open_entry(
        service
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "broker snapshot quantity does not match"
        ),
    ):
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=(
                result.execution_result
            ),
        )



def test_partially_filled_cancel_keeps_entry_reserved() -> None:
    service, broker, _ = make_service()

    signal, result = execute_open_entry(
        service
    )

    broker.current_status = (
        BrokerOrderStatus.CANCELLED
    )
    broker.filled_quantity = 20
    broker.average_price = 100.40

    snapshot = (
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=(
                result.execution_result
            ),
        )
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.CANCELLED
    )

    assert snapshot.filled_quantity == 20

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert (
        service.idempotency_guard
        .get(key)
        .state
        is IdempotencyState.SUBMITTED
    )


def test_filled_status_requires_full_requested_quantity() -> None:
    service, broker, state_machine = (
        make_service()
    )

    _, result = execute_open_entry(
        service
    )

    broker.current_status = (
        BrokerOrderStatus.FILLED
    )
    broker.filled_quantity = 20
    broker.average_price = 100.40

    with pytest.raises(
        RuntimeError,
        match=(
            "FILLED broker snapshot must prove "
            "full entry quantity"
        ),
    ):
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=(
                result.execution_result
            ),
        )

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.OPEN
    )


def test_filled_status_requires_average_fill_price() -> None:
    service, broker, state_machine = (
        make_service()
    )

    _, result = execute_open_entry(
        service
    )

    broker.current_status = (
        BrokerOrderStatus.FILLED
    )
    broker.filled_quantity = 65
    broker.average_price = None

    with pytest.raises(
        RuntimeError,
        match=(
            "FILLED broker snapshot requires "
            "average fill price"
        ),
    ):
        service.refresh_entry_order_status(
            intent=result.intent,
            execution_result=(
                result.execution_result
            ),
        )

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.OPEN
    )
