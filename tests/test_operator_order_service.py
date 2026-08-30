from __future__ import annotations

from datetime import date
from datetime import datetime

import pytest

from src.api.operator_orders import (
    OperatorOrderService,
)
from src.database.schema import (
    OrderRecord,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
    RuntimeSnapshot,
    RuntimeState,
)


NOW = datetime(
    2026,
    8,
    31,
    11,
    30,
)

CAPTURED_AT = datetime(
    2026,
    8,
    31,
    11,
    31,
)

RUNTIME_ID = "M13-RUNTIME-ORDERS"


def make_runtime_snapshot(
) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        runtime_id=RuntimeId(
            RUNTIME_ID
        ),
        trading_date=date(
            2026,
            8,
            31,
        ),
        mode=RuntimeMode.DRY_RUN,
        state=RuntimeState.RUNNING,
        started_at=NOW,
        updated_at=NOW,
        stopped_at=None,
        failure=None,
        recovery_required=False,
        recovered=False,
    )


class FakeRuntime:
    def __init__(
        self,
    ) -> None:
        self.read_count = 0

    @property
    def snapshot(
        self,
    ) -> RuntimeSnapshot:
        self.read_count += 1

        return make_runtime_snapshot()


def make_order(
    *,
    order_id: str,
    side: str,
    status: str,
    position_id: str | None,
    broker_order_id: str | None,
    filled_quantity: int,
    average_fill_price: float | None,
) -> OrderRecord:
    return OrderRecord(
        order_intent_id=order_id,
        runtime_id=RUNTIME_ID,
        signal_id=(
            "SIG-1"
            if side == "BUY"
            else None
        ),
        position_id=position_id,
        security_id="41009",
        symbol="NIFTY-CE",
        side=side,
        order_type=(
            "LIMIT"
            if side == "BUY"
            else "MARKET"
        ),
        reason=(
            "ENTRY"
            if side == "BUY"
            else "FORCE_EXIT"
        ),
        quantity=65,
        limit_price=(
            101.0
            if side == "BUY"
            else None
        ),
        execution_mode="DRY_RUN",
        status=status,
        broker_name=(
            "DHAN"
            if broker_order_id
            is not None
            else None
        ),
        broker_order_id=(
            broker_order_id
        ),
        filled_quantity=(
            filled_quantity
        ),
        average_fill_price=(
            average_fill_price
        ),
        created_at=NOW,
        submitted_at=NOW,
        updated_at=NOW,
    )


class FakeOrderRepository:
    def __init__(
        self,
        *,
        orders: tuple[
            OrderRecord,
            ...,
        ],
        open_orders: tuple[
            OrderRecord,
            ...,
        ],
    ) -> None:
        self.orders = orders
        self.open_orders = open_orders

        self.history_calls: list[
            str
        ] = []

        self.open_calls: list[
            str
        ] = []

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        self.history_calls.append(
            runtime_id
        )

        return self.orders

    def list_open_orders(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        self.open_calls.append(
            runtime_id
        )

        return self.open_orders


def test_order_projection_preserves_exact_owners() -> None:
    runtime = FakeRuntime()

    repository = FakeOrderRepository(
        orders=(),
        open_orders=(),
    )

    service = OperatorOrderService(
        runtime=runtime,
        order_repository=repository,
    )

    assert service.runtime is runtime

    assert (
        service.order_repository
        is repository
    )


def test_order_projection_maps_history_and_open_orders() -> None:
    submitted = make_order(
        order_id="ORD-1",
        side="BUY",
        status="SUBMITTED",
        position_id=None,
        broker_order_id="BROKER-1",
        filled_quantity=0,
        average_fill_price=None,
    )

    filled = make_order(
        order_id="EXIT-1",
        side="SELL",
        status="FILLED",
        position_id="POS-1",
        broker_order_id="BROKER-2",
        filled_quantity=65,
        average_fill_price=120.0,
    )

    runtime = FakeRuntime()

    repository = FakeOrderRepository(
        orders=(
            submitted,
            filled,
        ),
        open_orders=(
            submitted,
        ),
    )

    result = OperatorOrderService(
        runtime=runtime,
        order_repository=repository,
    ).capture(
        captured_at=CAPTURED_AT,
    )

    assert runtime.read_count == 1

    assert (
        repository.history_calls
        == [RUNTIME_ID]
    )

    assert (
        repository.open_calls
        == [RUNTIME_ID]
    )

    assert (
        result.runtime_id
        == RUNTIME_ID
    )

    assert result.total_count == 2
    assert result.open_count == 1

    assert (
        len(result.orders)
        == 2
    )

    assert (
        len(result.open_orders)
        == 1
    )

    first = result.orders[0]

    assert (
        first.order_intent_id
        == "ORD-1"
    )

    assert first.side == "BUY"

    assert (
        first.order_type
        == "LIMIT"
    )

    assert (
        first.limit_price
        == 101.0
    )

    assert (
        first.status
        == "SUBMITTED"
    )

    assert (
        first.broker_order_id
        == "BROKER-1"
    )

    second = result.orders[1]

    assert second.side == "SELL"

    assert (
        second.position_id
        == "POS-1"
    )

    assert (
        second.status
        == "FILLED"
    )

    assert (
        second.filled_quantity
        == 65
    )

    assert (
        second.average_fill_price
        == 120.0
    )

    assert (
        result.captured_at
        == CAPTURED_AT
    )


def test_empty_order_projection_is_valid() -> None:
    result = OperatorOrderService(
        runtime=FakeRuntime(),
        order_repository=(
            FakeOrderRepository(
                orders=(),
                open_orders=(),
            )
        ),
    ).capture(
        captured_at=CAPTURED_AT,
    )

    assert result.orders == ()
    assert result.open_orders == ()
    assert result.total_count == 0
    assert result.open_count == 0


def test_order_projection_rejects_non_datetime_capture() -> None:
    runtime = FakeRuntime()

    repository = FakeOrderRepository(
        orders=(),
        open_orders=(),
    )

    service = OperatorOrderService(
        runtime=runtime,
        order_repository=repository,
    )

    with pytest.raises(
        TypeError,
        match=(
            "captured_at must be "
            "a datetime"
        ),
    ):
        service.capture(
            captured_at=object(),  # type: ignore[arg-type]
        )

    assert runtime.read_count == 0
    assert repository.history_calls == []
    assert repository.open_calls == []
