from datetime import date, datetime

import pytest

from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
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
NOW = datetime(2026, 8, 7, 14, 30)


def make_signal() -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-M06-T05"
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


def make_selected_option() -> SelectedOption:
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


def make_intent() -> OrderIntent:
    return OrderIntent(
        intent_id=OrderIntentId(
            "ORD-M06-T05"
        ),
        signal=make_signal(),
        selected_option=make_selected_option(),
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=65,
        limit_price=206.0,
        execution_mode=ExecutionMode.DRY_RUN,
        created_at=NOW,
    )


class FakeExecutionProvider(
    BrokerExecutionProvider
):
    def __init__(self) -> None:
        self.submitted_intent = None
        self.cancelled_reference = None
        self.status_reference = None

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_order(
        self,
        intent: OrderIntent,
    ) -> ExecutionResult:
        self.submitted_intent = intent

        reference = BrokerOrderReference(
            broker_name=self.broker_name,
            order_id="ORDER-001",
        )

        return ExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=reference,
            submitted_at=NOW,
        )

    def cancel_order(
        self,
        broker_reference: BrokerOrderReference,
    ) -> BrokerCancellationResult:
        self.cancelled_reference = (
            broker_reference
        )

        return BrokerCancellationResult(
            broker_reference=broker_reference,
            success=True,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=NOW,
        )

    def get_order_status(
        self,
        broker_reference: BrokerOrderReference,
    ) -> BrokerOrderSnapshot:
        self.status_reference = (
            broker_reference
        )

        return BrokerOrderSnapshot(
            broker_reference=broker_reference,
            status=BrokerOrderStatus.OPEN,
            quantity=65,
            filled_quantity=0,
            average_price=None,
            updated_at=NOW,
        )


def test_fake_provider_implements_interface() -> None:
    provider = FakeExecutionProvider()

    assert isinstance(
        provider,
        BrokerExecutionProvider,
    )


def test_provider_name() -> None:
    provider = FakeExecutionProvider()

    assert provider.broker_name == "FAKE"


def test_submit_order_returns_execution_result() -> None:
    provider = FakeExecutionProvider()

    intent = make_intent()

    result = provider.submit_order(
        intent
    )

    assert result.success is True

    assert (
        result.status
        is BrokerOrderStatus.OPEN
    )

    assert result.broker_reference is not None

    assert (
        result.broker_reference.order_id
        == "ORDER-001"
    )

    assert (
        provider.submitted_intent
        is intent
    )


def test_cancel_order_returns_cancelled_result() -> None:
    provider = FakeExecutionProvider()

    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="ORDER-001",
    )

    result = provider.cancel_order(
        reference
    )

    assert result.success is True

    assert (
        result.status
        is BrokerOrderStatus.CANCELLED
    )

    assert (
        provider.cancelled_reference
        is reference
    )


def test_get_order_status_returns_snapshot() -> None:
    provider = FakeExecutionProvider()

    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="ORDER-001",
    )

    snapshot = provider.get_order_status(
        reference
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.OPEN
    )

    assert snapshot.quantity == 65
    assert snapshot.filled_quantity == 0

    assert (
        provider.status_reference
        is reference
    )


def test_order_snapshot_filled_quantity_cannot_be_negative() -> None:
    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="ORDER-001",
    )

    with pytest.raises(
        ValueError,
        match=(
            "filled_quantity cannot be negative"
        ),
    ):
        BrokerOrderSnapshot(
            broker_reference=reference,
            status=BrokerOrderStatus.OPEN,
            quantity=65,
            filled_quantity=-1,
            average_price=None,
            updated_at=NOW,
        )


def test_order_snapshot_filled_quantity_cannot_exceed_quantity() -> None:
    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="ORDER-001",
    )

    with pytest.raises(
        ValueError,
        match=(
            "filled_quantity cannot exceed quantity"
        ),
    ):
        BrokerOrderSnapshot(
            broker_reference=reference,
            status=BrokerOrderStatus.FILLED,
            quantity=65,
            filled_quantity=66,
            average_price=205.0,
            updated_at=NOW,
        )


def test_filled_snapshot_can_have_average_price() -> None:
    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="ORDER-001",
    )

    snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=65,
        filled_quantity=65,
        average_price=205.25,
        updated_at=NOW,
    )

    assert snapshot.filled_quantity == 65
    assert snapshot.average_price == 205.25


def test_invalid_average_price_rejected() -> None:
    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="ORDER-001",
    )

    with pytest.raises(
        ValueError,
        match=(
            "average_price must be greater than zero"
        ),
    ):
        BrokerOrderSnapshot(
            broker_reference=reference,
            status=BrokerOrderStatus.FILLED,
            quantity=65,
            filled_quantity=65,
            average_price=0,
            updated_at=NOW,
        )


def test_zero_snapshot_quantity_rejected() -> None:
    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="ORDER-001",
    )

    with pytest.raises(
        ValueError,
        match="quantity must be greater than zero",
    ):
        BrokerOrderSnapshot(
            broker_reference=reference,
            status=BrokerOrderStatus.OPEN,
            quantity=0,
            filled_quantity=0,
            average_price=None,
            updated_at=NOW,
        )


def test_cancellation_result_can_represent_failure() -> None:
    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="ORDER-001",
    )

    result = BrokerCancellationResult(
        broker_reference=reference,
        success=False,
        status=BrokerOrderStatus.OPEN,
        cancelled_at=NOW,
        message="Order could not be cancelled",
    )

    assert result.success is False
    assert result.status is BrokerOrderStatus.OPEN