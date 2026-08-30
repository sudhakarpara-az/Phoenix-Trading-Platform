from __future__ import annotations

import asyncio
import json

from datetime import datetime
from typing import Any
from typing import cast

import pytest

from starlette.types import Message
from starlette.types import Scope

from src.api.operator_http import (
    build_operator_http_app,
)
from src.api.operator_orders import (
    OperatorOrderView,
    OperatorOrdersView,
)
from src.api.operator_transport import (
    OperatorOrdersRequest,
    OperatorTransportService,
)


CAPTURED_AT = datetime(
    2026,
    8,
    31,
    12,
    0,
)


ORDER = OperatorOrderView(
    order_intent_id="ORD-1",
    runtime_id="RUNTIME-1",
    signal_id="SIG-1",
    position_id=None,
    security_id="41009",
    symbol="NIFTY-CE",
    side="BUY",
    order_type="LIMIT",
    reason="ENTRY",
    quantity=65,
    limit_price=101.0,
    execution_mode="LIVE",
    status="SUBMITTED",
    broker_name="DHAN",
    broker_order_id="DHAN-1",
    filled_quantity=0,
    average_fill_price=None,
    created_at=CAPTURED_AT,
    submitted_at=CAPTURED_AT,
    updated_at=CAPTURED_AT,
)


ORDERS_VIEW = OperatorOrdersView(
    runtime_id="RUNTIME-1",
    orders=(ORDER,),
    open_orders=(ORDER,),
    total_count=1,
    open_count=1,
    captured_at=CAPTURED_AT,
)


class FakeOrders:
    def __init__(
        self,
    ) -> None:
        self.calls: list[
            datetime
        ] = []

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorOrdersView:
        self.calls.append(
            captured_at
        )

        return ORDERS_VIEW


class UnusedStatus:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError


class UnusedStrategy:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError


class UnusedNotifications:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError


class UnusedScheduler:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError


class UnusedPositions:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError


class UnusedReporting:
    def current_runtime_json(
        self,
        *,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        raise AssertionError

    def daily_trade_json(
        self,
        *,
        trading_date,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        raise AssertionError


class UnusedControl:
    def exit_and_stop(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> Any:
        raise AssertionError

    def resume(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> Any:
        raise AssertionError


def make_transport(
    orders: FakeOrders,
) -> OperatorTransportService:
    return OperatorTransportService(
        status=UnusedStatus(),
        strategy=UnusedStrategy(),
        notifications=UnusedNotifications(),
        scheduler=UnusedScheduler(),
        positions=UnusedPositions(),
        orders=orders,
        reporting=UnusedReporting(),
        control=UnusedControl(),
    )


def test_order_transport_preserves_exact_owner() -> None:
    orders = FakeOrders()

    transport = make_transport(
        orders
    )

    assert transport.orders is orders


def test_order_transport_delegates_once() -> None:
    orders = FakeOrders()

    result = make_transport(
        orders
    ).get_orders(
        OperatorOrdersRequest(
            captured_at=CAPTURED_AT,
        )
    )

    assert result is ORDERS_VIEW

    assert orders.calls == [
        CAPTURED_AT,
    ]


def test_order_transport_rejects_wrong_request() -> None:
    transport = make_transport(
        FakeOrders()
    )

    with pytest.raises(
        TypeError,
        match="OperatorOrdersRequest",
    ):
        transport.get_orders(
            object(),  # type: ignore[arg-type]
        )


def test_order_http_uses_public_asgi_contract() -> None:
    orders = FakeOrders()

    transport = make_transport(
        orders
    )

    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls

        clock_calls += 1

        return CAPTURED_AT

    app = build_operator_http_app(
        transport=transport,
        clock=clock,
    )

    async def request_orders(
    ) -> list[Message]:

        messages: list[
            Message
        ] = []

        delivered = False

        async def receive(
        ) -> Message:
            nonlocal delivered

            if not delivered:
                delivered = True

                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

            return {
                "type": "http.disconnect",
            }

        async def send(
            message: Message,
        ) -> None:
            messages.append(
                message
            )

        scope = cast(
            Scope,
            {
                "type": "http",
                "asgi": {
                    "version": "3.0",
                    "spec_version": "2.3",
                },
                "http_version": "1.1",
                "server": (
                    "testserver",
                    80,
                ),
                "client": (
                    "127.0.0.1",
                    12345,
                ),
                "scheme": "http",
                "method": "GET",
                "root_path": "",
                "path": (
                    "/api/v1/operator/"
                    "orders"
                ),
                "raw_path": (
                    b"/api/v1/operator/"
                    b"orders"
                ),
                "query_string": b"",
                "headers": [
                    (
                        b"host",
                        b"testserver",
                    ),
                ],
                "state": {},
            },
        )

        await app(
            scope,
            receive,
            send,
        )

        return messages

    messages = asyncio.run(
        request_orders()
    )

    start = next(
        message
        for message in messages
        if (
            message.get("type")
            == "http.response.start"
        )
    )

    assert start.get(
        "status"
    ) == 200

    body = b"".join(
        cast(
            bytes,
            message.get(
                "body",
                b"",
            ),
        )
        for message in messages
        if (
            message.get("type")
            == "http.response.body"
        )
    )

    payload = json.loads(
        body.decode("utf-8")
    )

    assert clock_calls == 1

    assert orders.calls == [
        CAPTURED_AT,
    ]

    assert (
        payload["runtime_id"]
        == "RUNTIME-1"
    )

    assert (
        payload["total_count"]
        == 1
    )

    assert (
        payload["open_count"]
        == 1
    )

    assert (
        len(payload["orders"])
        == 1
    )

    assert (
        len(
            payload["open_orders"]
        )
        == 1
    )

    order = payload["orders"][0]

    assert (
        order["order_intent_id"]
        == "ORD-1"
    )

    assert order["side"] == "BUY"

    assert (
        order["status"]
        == "SUBMITTED"
    )

    assert (
        order["broker_order_id"]
        == "DHAN-1"
    )

    assert (
        order["filled_quantity"]
        == 0
    )
