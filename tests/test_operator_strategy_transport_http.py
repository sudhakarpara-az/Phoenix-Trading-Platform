from __future__ import annotations

import asyncio
import json

from datetime import date
from datetime import datetime
from typing import Any, cast

import pytest

from starlette.types import Message
from starlette.types import Scope

from src.api.operator_http import (
    build_operator_http_app,
)
from src.api.operator_strategy import (
    OperatorKSLevelsView,
    OperatorSelectedOptionView,
    OperatorStrategyView,
)
from src.api.operator_transport import (
    OperatorStrategyRequest,
    OperatorTransportService,
)


CAPTURED_AT = datetime(
    2026,
    8,
    31,
    9,
    20,
)

TRADING_DATE = date(
    2026,
    8,
    31,
)

EXPIRY = date(
    2026,
    9,
    3,
)


def make_option(
    *,
    symbol: str,
    security_id: str,
    option_type: str,
    delta: float,
) -> OperatorSelectedOptionView:
    return OperatorSelectedOptionView(
        underlying_symbol="NIFTY",
        symbol=symbol,
        security_id=security_id,
        option_type=option_type,
        strike=25000.0,
        expiry=EXPIRY,
        lot_size=65,
        delta=delta,
        delta_magnitude=abs(delta),
        selection_ltp=100.0,
        selected_at=CAPTURED_AT,
        selection_delta_target=0.60,
    )


def make_levels(
    *,
    symbol: str,
    security_id: str,
    base: float,
) -> OperatorKSLevelsView:
    return OperatorKSLevelsView(
        trading_date=TRADING_DATE,
        instrument_security_id=security_id,
        instrument_symbol=symbol,
        high_915=110.0,
        low_915=95.0,
        close_915=105.0,
        n1=1.0,
        n2=2.0,
        c1=3.0,
        e_level=base + 1.0,
        t_level=base + 2.0,
        k0=base,
        k1=base + 1.0,
        k2=base + 2.0,
        k3=base + 3.0,
        k5=base + 5.0,
        k6=base + 6.0,
        k7=base + 7.0,
        calculated_at=CAPTURED_AT,
        formula_version="test-v1",
    )


STRATEGY_VIEW = OperatorStrategyView(
    trading_date=TRADING_DATE,
    expiry=EXPIRY,
    selected_call=make_option(
        symbol="NIFTY-CALL",
        security_id="CALL-1",
        option_type="CALL",
        delta=0.61,
    ),
    selected_put=make_option(
        symbol="NIFTY-PUT",
        security_id="PUT-1",
        option_type="PUT",
        delta=-0.62,
    ),
    call_levels=make_levels(
        symbol="NIFTY-CALL",
        security_id="CALL-1",
        base=100.0,
    ),
    put_levels=make_levels(
        symbol="NIFTY-PUT",
        security_id="PUT-1",
        base=200.0,
    ),
    prepared_at=CAPTURED_AT,
    captured_at=CAPTURED_AT,
    is_ready=True,
)


class FakeStrategy:
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
    ) -> OperatorStrategyView:
        self.calls.append(
            captured_at
        )

        return STRATEGY_VIEW


class UnusedStatus:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError(
            "status must not be called"
        )


class UnusedNotifications:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError(
            "notifications must not be called"
        )


class UnusedReporting:
    def current_runtime_json(
        self,
        *,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        raise AssertionError(
            "runtime report must not be called"
        )

    def daily_trade_json(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        raise AssertionError(
            "daily report must not be called"
        )


class UnusedScheduler:
    def capture(
        self,
        *,
        captured_at,
    ):
        raise AssertionError(
            "scheduler must not be called"
        )


class UnusedControl:
    def exit_and_stop(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> Any:
        raise AssertionError(
            "control write must not be called"
        )

    def resume(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> Any:
        raise AssertionError(
            "control write must not be called"
        )


def make_transport(
    strategy: FakeStrategy,
) -> OperatorTransportService:
    return OperatorTransportService(
        status=UnusedStatus(),
        strategy=strategy,
        notifications=UnusedNotifications(),
        scheduler=UnusedScheduler(),
        reporting=UnusedReporting(),
        control=UnusedControl(),
    )


def test_transport_preserves_exact_strategy_service() -> None:
    strategy = FakeStrategy()

    transport = make_transport(
        strategy
    )

    assert (
        transport.strategy
        is strategy
    )


def test_transport_strategy_delegates_exactly_once() -> None:
    strategy = FakeStrategy()

    transport = make_transport(
        strategy
    )

    result = transport.get_strategy(
        OperatorStrategyRequest(
            captured_at=CAPTURED_AT,
        )
    )

    assert result is STRATEGY_VIEW

    assert strategy.calls == [
        CAPTURED_AT,
    ]


def test_transport_strategy_rejects_wrong_request() -> None:
    strategy = FakeStrategy()

    transport = make_transport(
        strategy
    )

    with pytest.raises(
        TypeError,
        match="OperatorStrategyRequest",
    ):
        transport.get_strategy(
            object(),  # type: ignore[arg-type]
        )


def test_http_strategy_route_uses_injected_clock_once() -> None:
    strategy = FakeStrategy()

    transport = make_transport(
        strategy
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

    async def request_strategy(
    ) -> list[Message]:
        messages: list[
            Message
        ] = []

        request_delivered = False

        async def receive(
        ) -> Message:
            nonlocal request_delivered

            if not request_delivered:
                request_delivered = True

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
                    "strategy"
                ),
                "raw_path": (
                    b"/api/v1/operator/"
                    b"strategy"
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
        request_strategy()
    )

    response_start = next(
        message
        for message in messages
        if (
            message.get("type")
            == "http.response.start"
        )
    )

    assert (
        response_start["status"]
        == 200
    )

    response_body = b"".join(
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
        response_body.decode(
            "utf-8"
        )
    )

    assert clock_calls == 1

    assert strategy.calls == [
        CAPTURED_AT,
    ]

    assert (
        payload["trading_date"]
        == "2026-08-31"
    )

    assert (
        payload["expiry"]
        == "2026-09-03"
    )

    assert (
        payload["selected_call"]["symbol"]
        == "NIFTY-CALL"
    )

    assert (
        payload["selected_call"]["delta"]
        == pytest.approx(0.61)
    )

    assert (
        payload["selected_put"]["symbol"]
        == "NIFTY-PUT"
    )

    assert (
        payload["selected_put"]["delta"]
        == pytest.approx(-0.62)
    )

    assert (
        payload["call_levels"]["k5"]
        == pytest.approx(105.0)
    )

    assert (
        payload["put_levels"]["k7"]
        == pytest.approx(207.0)
    )

    assert payload["is_ready"] is True
