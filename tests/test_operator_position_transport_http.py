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
from src.api.operator_positions import (
    OperatorPositionView,
    OperatorPositionsView,
)
from src.api.operator_transport import (
    OperatorPositionsRequest,
    OperatorTransportService,
)


CAPTURED_AT = datetime(
    2026,
    8,
    31,
    11,
    0,
)


POSITION_VIEW = (
    OperatorPositionView(
        position_id="POS-1",
        risk_id="RISK-1",
        symbol="NIFTY-CE",
        security_id="101",
        lot_size=65,
        entry_price=100.0,
        original_quantity=65,
        open_quantity=65,
        closed_quantity=0,
        state="OPEN",
        realized_pnl=0.0,
        pnl_available=True,
        unrealized_pnl=650.0,
        total_pnl=650.0,
        unrealized_points=10.0,
        latest_ltp=110.0,
        latest_mark_at=datetime(
            2026,
            8,
            31,
            10,
            59,
        ),
        created_at=datetime(
            2026,
            8,
            31,
            9,
            35,
        ),
        updated_at=datetime(
            2026,
            8,
            31,
            10,
            59,
        ),
    )
)


POSITIONS_VIEW = (
    OperatorPositionsView(
        positions=(
            POSITION_VIEW,
        ),
        open_count=1,
        open_quantity=65,
        realized_pnl=0.0,
        unrealized_pnl=650.0,
        total_pnl=650.0,
        captured_at=CAPTURED_AT,
    )
)


class _UnusedOrders:
    def capture(
        self,
        *,
        captured_at,
    ):
        raise AssertionError(
            "orders must not be called"
        )


class FakePositions:
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
    ) -> OperatorPositionsView:
        self.calls.append(
            captured_at
        )

        return POSITIONS_VIEW


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
    positions: FakePositions,
) -> OperatorTransportService:
    return OperatorTransportService(
        status=UnusedStatus(),
        strategy=UnusedStrategy(),
        notifications=UnusedNotifications(),
        scheduler=UnusedScheduler(),
        positions=positions,
        orders=_UnusedOrders(),
        reporting=UnusedReporting(),
        control=UnusedControl(),
    )


def test_position_transport_preserves_exact_owner() -> None:
    positions = FakePositions()

    transport = make_transport(
        positions
    )

    assert (
        transport.positions
        is positions
    )


def test_position_transport_delegates_once() -> None:
    positions = FakePositions()

    transport = make_transport(
        positions
    )

    result = transport.get_positions(
        OperatorPositionsRequest(
            captured_at=CAPTURED_AT,
        )
    )

    assert result is POSITIONS_VIEW

    assert positions.calls == [
        CAPTURED_AT,
    ]


def test_position_transport_rejects_wrong_request() -> None:
    transport = make_transport(
        FakePositions()
    )

    with pytest.raises(
        TypeError,
        match="OperatorPositionsRequest",
    ):
        transport.get_positions(
            object(),  # type: ignore[arg-type]
        )


def test_position_http_uses_public_asgi_contract() -> None:
    positions = FakePositions()

    transport = make_transport(
        positions
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

    async def request_positions(
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
                    "positions"
                ),
                "raw_path": (
                    b"/api/v1/operator/"
                    b"positions"
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
        request_positions()
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
        body.decode(
            "utf-8"
        )
    )

    assert clock_calls == 1

    assert positions.calls == [
        CAPTURED_AT,
    ]

    assert (
        payload["open_count"]
        == 1
    )

    assert (
        payload["open_quantity"]
        == 65
    )

    assert (
        payload["unrealized_pnl"]
        == 650.0
    )

    assert (
        payload["total_pnl"]
        == 650.0
    )

    assert (
        len(
            payload["positions"]
        )
        == 1
    )

    position = (
        payload["positions"][0]
    )

    assert (
        position["position_id"]
        == "POS-1"
    )

    assert (
        position["latest_ltp"]
        == 110.0
    )

    assert (
        position["unrealized_points"]
        == 10.0
    )

    assert (
        position["pnl_available"]
        is True
    )
