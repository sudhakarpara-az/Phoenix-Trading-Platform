from datetime import datetime

from src.execution.dhan_exit_order_adapter import (
    DhanExitOrderAdapter,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
)
from src.execution.exit_execution_provider import (
    ExitOrderIntent,
    ExitOrderIntentId,
    ExitTransactionType,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitReason,
    FilledPositionId,
)
from src.option_selection.option_types import (
    OptionType,
)


NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


def make_target_intent(
    *,
    intent_id: str = "EXIT-M06-T18",
    price: float = 126.0,
) -> ExitOrderIntent:
    return ExitOrderIntent(
        intent_id=ExitOrderIntentId(
            intent_id
        ),
        position_id=FilledPositionId(
            "POS-M06-T18"
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
        quantity=65,
        price=price,
        reason=ExitReason.TARGET,
        created_at=NOW,
    )


def make_force_exit_intent() -> ExitOrderIntent:
    return ExitOrderIntent(
        intent_id=ExitOrderIntentId(
            "EXIT-FORCE-T18"
        ),
        position_id=FilledPositionId(
            "POS-M06-T18"
        ),
        security_id="41009",
        symbol=(
            "NIFTY50-20260811-24450-CE"
        ),
        option_type=OptionType.CALL,
        transaction_type=(
            ExitTransactionType.SELL
        ),
        order_type=ExitOrderType.MARKET,
        quantity=65,
        price=None,
        reason=ExitReason.FORCE_EXIT,
        created_at=NOW,
    )


class FakeDhanClient:
    def __init__(self) -> None:
        self.place_kwargs = None
        self.cancelled_order_id = None
        self.status_order_id = None

        self.place_response = {
            "orderId": "DHAN-EXIT-001",
            "orderStatus": "PENDING",
        }

        self.cancel_response = {
            "orderId": "DHAN-EXIT-001",
            "orderStatus": "CANCELLED",
        }

        self.status_response = {
            "orderId": "DHAN-EXIT-001",
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
    adapter = DhanExitOrderAdapter(
        FakeDhanClient()
    )

    assert adapter.broker_name == "DHAN"


def test_target_exit_maps_to_dhan_sell_limit() -> None:
    client = FakeDhanClient()

    adapter = DhanExitOrderAdapter(
        client
    )

    result = adapter.submit_exit(
        make_target_intent()
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
        == "SELL"
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
        == 126.0
    )

    assert (
        client.place_kwargs[
            "validity"
        ]
        == "DAY"
    )


def test_force_exit_maps_to_market_sell() -> None:
    client = FakeDhanClient()

    adapter = DhanExitOrderAdapter(
        client
    )

    result = adapter.submit_exit(
        make_force_exit_intent()
    )

    assert result.success is True

    assert (
        client.place_kwargs[
            "transaction_type"
        ]
        == "SELL"
    )

    assert (
        client.place_kwargs[
            "order_type"
        ]
        == "MARKET"
    )

    assert (
        client.place_kwargs[
            "price"
        ]
        == 0
    )


def test_pending_maps_to_pending() -> None:
    result = DhanExitOrderAdapter(
        FakeDhanClient()
    ).submit_exit(
        make_target_intent()
    )

    assert (
        result.status
        is BrokerOrderStatus.PENDING
    )

    assert (
        result.broker_reference
        is not None
    )


def test_transit_maps_to_pending() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "orderId": "DHAN-EXIT-001",
        "orderStatus": "TRANSIT",
    }

    result = DhanExitOrderAdapter(
        client
    ).submit_exit(
        make_target_intent()
    )

    assert (
        result.status
        is BrokerOrderStatus.PENDING
    )


def test_traded_maps_to_filled() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "orderId": "DHAN-EXIT-001",
        "orderStatus": "TRADED",
    }

    result = DhanExitOrderAdapter(
        client
    ).submit_exit(
        make_target_intent()
    )

    assert result.success is True

    assert (
        result.status
        is BrokerOrderStatus.FILLED
    )


def test_rejected_exit_fails_closed() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "orderId": "DHAN-EXIT-001",
        "orderStatus": "REJECTED",
        "omsErrorDescription": (
            "Exit rejected"
        ),
    }

    result = DhanExitOrderAdapter(
        client
    ).submit_exit(
        make_target_intent()
    )

    assert result.success is False

    assert (
        result.status
        is BrokerOrderStatus.REJECTED
    )

    assert (
        result.broker_reference
        is None
    )

    assert (
        result.message
        == "Exit rejected"
    )


def test_sdk_wrapped_response_supported() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "status": "success",
        "remarks": "",
        "data": {
            "orderId": "DHAN-EXIT-002",
            "orderStatus": "PENDING",
        },
    }

    result = DhanExitOrderAdapter(
        client
    ).submit_exit(
        make_target_intent()
    )

    assert result.success is True

    assert (
        result.broker_reference
        is not None
    )

    assert (
        result.broker_reference.order_id
        == "DHAN-EXIT-002"
    )


def test_missing_order_id_fails_closed() -> None:
    client = FakeDhanClient()

    client.place_response = {
        "orderStatus": "PENDING",
    }

    result = DhanExitOrderAdapter(
        client
    ).submit_exit(
        make_target_intent()
    )

    assert result.success is False

    assert (
        result.broker_reference
        is None
    )


def test_submission_exception_fails_closed() -> None:
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

    result = DhanExitOrderAdapter(
        BrokenClient()
    ).submit_exit(
        make_target_intent()
    )

    assert result.success is False

    assert (
        result.status
        is BrokerOrderStatus.UNKNOWN
    )

    assert result.message is not None

    assert (
        "network failure"
        in result.message
    )


def test_correlation_id_is_capped_at_30_chars() -> None:
    client = FakeDhanClient()

    adapter = DhanExitOrderAdapter(
        client
    )

    intent = make_target_intent(
        intent_id=(
            "EXIT-THIS-IS-A-VERY-LONG-"
            "PHOENIX-EXIT-ORDER-ID"
        )
    )

    adapter.submit_exit(
        intent
    )

    correlation_id = (
        client.place_kwargs[
            "correlation_id"
        ]
    )

    assert (
        len(correlation_id)
        <= 30
    )


def test_cancel_exit() -> None:
    client = FakeDhanClient()

    adapter = DhanExitOrderAdapter(
        client
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="DHAN-EXIT-001",
    )

    result = adapter.cancel_exit(
        reference
    )

    assert result.success is True

    assert (
        result.status
        is BrokerOrderStatus.CANCELLED
    )

    assert (
        client.cancelled_order_id
        == "DHAN-EXIT-001"
    )


def test_wrong_broker_reference_rejected() -> None:
    adapter = DhanExitOrderAdapter(
        FakeDhanClient()
    )

    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="123",
    )

    try:
        adapter.cancel_exit(
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


def test_get_pending_exit_status() -> None:
    client = FakeDhanClient()

    adapter = DhanExitOrderAdapter(
        client
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="DHAN-EXIT-001",
    )

    snapshot = adapter.get_exit_status(
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
        == "DHAN-EXIT-001"
    )


def test_partial_exit_is_normalized() -> None:
    client = FakeDhanClient()

    client.status_response = {
        "orderId": "DHAN-EXIT-001",
        "orderStatus": "PART_TRADED",
        "quantity": 65,
        "filledQty": 30,
        "averageTradedPrice": 126.0,
        "updateTime": (
            "2026-08-07 14:31:00"
        ),
    }

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="DHAN-EXIT-001",
    )

    snapshot = DhanExitOrderAdapter(
        client
    ).get_exit_status(
        reference
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.PARTIALLY_FILLED
    )

    assert (
        snapshot.filled_quantity
        == 30
    )

    assert (
        snapshot.average_price
        == 126.0
    )


def test_filled_exit_is_normalized() -> None:
    client = FakeDhanClient()

    client.status_response = {
        "orderId": "DHAN-EXIT-001",
        "orderStatus": "TRADED",
        "quantity": 65,
        "filledQty": 65,
        "averageTradedPrice": 126.25,
        "updateTime": (
            "2026-08-07 14:31:00"
        ),
    }

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="DHAN-EXIT-001",
    )

    snapshot = DhanExitOrderAdapter(
        client
    ).get_exit_status(
        reference
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.FILLED
    )

    assert (
        snapshot.filled_quantity
        == 65
    )

    assert (
        snapshot.average_price
        == 126.25
    )