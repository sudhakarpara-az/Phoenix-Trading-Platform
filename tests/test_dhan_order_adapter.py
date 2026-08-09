from datetime import date, datetime

from src.execution.dhan_order_adapter import (
    DhanOrderAdapter,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
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
            "SIG-M06-T06"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        instrument_security_id="41009",
        instrument_symbol="NIFTY50-20260811-24450-CE",
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500,
        level_price=24500,
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
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=205,
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


def make_intent(
    intent_id: str = "ORD-M06-T06",
) -> OrderIntent:
    return OrderIntent(
        intent_id=OrderIntentId(
            intent_id
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


class FakeDhanClient:
    def __init__(self) -> None:
        self.place_kwargs = None
        self.cancelled_order_id = None
        self.status_order_id = None

        self.place_response = {
            "orderId": "DHAN-001",
            "orderStatus": "PENDING",
        }

        self.cancel_response = {
            "orderId": "DHAN-001",
            "orderStatus": "CANCELLED",
        }

        self.status_response = {
            "orderId": "DHAN-001",
            "orderStatus": "PENDING",
            "quantity": 65,
            "filledQty": 0,
            "averageTradedPrice": 0,
            "updateTime": (
                "2026-08-07 14:30:05"
            ),
        }

    def place_order(
        self,
        **kwargs,
    ):
        self.place_kwargs = kwargs

        return self.place_response

    def cancel_order(
        self,
        *,
        order_id,
    ):
        self.cancelled_order_id = (
            order_id
        )

        return self.cancel_response

    def get_order_by_id(
        self,
        *,
        order_id,
    ):
        self.status_order_id = (
            order_id
        )

        return self.status_response


def test_broker_name() -> None:
    adapter = DhanOrderAdapter(
        FakeDhanClient()
    )

    assert adapter.broker_name == "DHAN"


def test_submit_order_maps_phoenix_fields() -> None:
    client = FakeDhanClient()

    adapter = DhanOrderAdapter(
        client
    )

    result = adapter.submit_order(
        make_intent()
    )

    assert result.success is True

    assert client.place_kwargs is not None

    assert (
        client.place_kwargs[
            "security_id"
        ]
        == "41009"
    )

    assert (
        client.place_kwargs[
            "exchange_segment"
        ]
        == "NSE_FNO"
    )

    assert (
        client.place_kwargs[
            "transaction_type"
        ]
        == "BUY"
    )

    assert (
        client.place_kwargs[
            "quantity"
        ]
        == 65
    )

    assert (
        client.place_kwargs[
            "order_type"
        ]
        == "LIMIT"
    )

    assert (
        client.place_kwargs[
            "product_type"
        ]
        == "INTRADAY"
    )

    assert (
        client.place_kwargs[
            "price"
        ]
        == 206.0
    )

    assert (
        client.place_kwargs[
            "validity"
        ]
        == "DAY"
    )


def test_submit_pending_maps_to_pending() -> None:
    adapter = DhanOrderAdapter(
        FakeDhanClient()
    )

    result = adapter.submit_order(
        make_intent()
    )

    assert (
        result.status
        is BrokerOrderStatus.PENDING
    )

    assert result.broker_reference is not None

    assert (
        result.broker_reference.order_id
        == "DHAN-001"
    )


def test_submit_transit_maps_to_pending() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "orderId": "DHAN-001",
        "orderStatus": "TRANSIT",
    }

    result = DhanOrderAdapter(
        client
    ).submit_order(
        make_intent()
    )

    assert (
        result.status
        is BrokerOrderStatus.PENDING
    )


def test_submit_traded_maps_to_filled() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "orderId": "DHAN-001",
        "orderStatus": "TRADED",
    }

    result = DhanOrderAdapter(
        client
    ).submit_order(
        make_intent()
    )

    assert result.success is True

    assert (
        result.status
        is BrokerOrderStatus.FILLED
    )


def test_rejected_order_fails_closed() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "orderId": "DHAN-001",
        "orderStatus": "REJECTED",
        "omsErrorDescription": (
            "Insufficient balance"
        ),
    }

    result = DhanOrderAdapter(
        client
    ).submit_order(
        make_intent()
    )

    assert result.success is False

    assert (
        result.status
        is BrokerOrderStatus.REJECTED
    )

    assert result.broker_reference is None

    assert (
        result.message
        == "Insufficient balance"
    )


def test_sdk_wrapped_submission_response() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "status": "success",
        "remarks": "",
        "data": {
            "orderId": "DHAN-002",
            "orderStatus": "PENDING",
        },
    }

    result = DhanOrderAdapter(
        client
    ).submit_order(
        make_intent()
    )

    assert result.success is True

    assert result.broker_reference is not None

    assert (
        result.broker_reference.order_id
        == "DHAN-002"
    )


def test_missing_order_id_fails_closed() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "orderStatus": "PENDING",
    }

    result = DhanOrderAdapter(
        client
    ).submit_order(
        make_intent()
    )

    assert result.success is False

    assert result.broker_reference is None


def test_exception_during_submission_fails_closed() -> None:
    class BrokenClient(
        FakeDhanClient
    ):
        def place_order(
            self,
            **kwargs,
        ):
            raise RuntimeError(
                "network failure"
            )

    result = DhanOrderAdapter(
        BrokenClient()
    ).submit_order(
        make_intent()
    )

    assert result.success is False

    assert (
        result.status
        is BrokerOrderStatus.UNKNOWN
    )

    assert (
        "network failure"
        in result.message
    )


def test_correlation_id_is_capped_at_30_chars() -> None:
    client = FakeDhanClient()

    adapter = DhanOrderAdapter(
        client
    )

    intent = make_intent(
        intent_id=(
            "ORD-THIS-IS-A-VERY-LONG-"
            "PHOENIX-ORDER-ID"
        )
    )

    adapter.submit_order(
        intent
    )

    correlation_id = (
        client.place_kwargs[
            "correlation_id"
        ]
    )

    assert len(
        correlation_id
    ) <= 30


def test_cancel_order() -> None:
    client = FakeDhanClient()

    adapter = DhanOrderAdapter(
        client
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="DHAN-001",
    )

    result = adapter.cancel_order(
        reference
    )

    assert result.success is True

    assert (
        result.status
        is BrokerOrderStatus.CANCELLED
    )

    assert (
        client.cancelled_order_id
        == "DHAN-001"
    )


def test_wrong_broker_reference_is_rejected() -> None:
    adapter = DhanOrderAdapter(
        FakeDhanClient()
    )

    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="123",
    )

    try:
        adapter.cancel_order(
            reference
        )

        assert False, (
            "Expected ValueError"
        )

    except ValueError as exc:
        assert (
            "does not belong to DHAN"
            in str(exc)
        )


def test_get_pending_order_status() -> None:
    client = FakeDhanClient()

    adapter = DhanOrderAdapter(
        client
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="DHAN-001",
    )

    snapshot = adapter.get_order_status(
        reference
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.PENDING
    )

    assert snapshot.quantity == 65
    assert snapshot.filled_quantity == 0

    assert (
        client.status_order_id
        == "DHAN-001"
    )


def test_partial_trade_is_normalized() -> None:
    client = FakeDhanClient()

    client.status_response = {
        "orderId": "DHAN-001",
        "orderStatus": "PART_TRADED",
        "quantity": 65,
        "filledQty": 25,
        "averageTradedPrice": 205.25,
        "updateTime": (
            "2026-08-07 14:30:05"
        ),
    }

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="DHAN-001",
    )

    snapshot = DhanOrderAdapter(
        client
    ).get_order_status(
        reference
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.PARTIALLY_FILLED
    )

    assert snapshot.filled_quantity == 25

    assert (
        snapshot.average_price
        == 205.25
    )


def test_traded_order_is_normalized() -> None:
    client = FakeDhanClient()

    client.status_response = {
        "orderId": "DHAN-001",
        "orderStatus": "TRADED",
        "quantity": 65,
        "filledQty": 65,
        "averageTradedPrice": 205.50,
        "updateTime": (
            "2026-08-07 14:30:05"
        ),
    }

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="DHAN-001",
    )

    snapshot = DhanOrderAdapter(
        client
    ).get_order_status(
        reference
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.FILLED
    )

    assert snapshot.filled_quantity == 65

    assert snapshot.average_price == 205.50