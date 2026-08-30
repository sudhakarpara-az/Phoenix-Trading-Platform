from __future__ import annotations

import asyncio
import json

from datetime import date
from datetime import datetime
from typing import Any
from typing import cast

import pytest

from starlette.types import Message
from starlette.types import Scope

from src.api.operator_http import (
    build_operator_http_app,
)
from src.api.operator_scheduler import (
    OperatorSchedulerView,
)
from src.api.operator_transport import (
    OperatorSchedulerRequest,
    OperatorTransportService,
)


CAPTURED_AT = datetime(
    2026,
    8,
    31,
    9,
    20,
)


SCHEDULER_VIEW = OperatorSchedulerView(
    trading_date=date(
        2026,
        8,
        31,
    ),
    state="MONITORING",
    updated_at=datetime(
        2026,
        8,
        31,
        9,
        20,
    ),
    started_at=datetime(
        2026,
        8,
        31,
        9,
        0,
    ),
    closed_at=None,
    failure_message=None,
    is_terminal=False,
    can_accept_new_entries=True,
    can_manage_positions=True,
    captured_at=CAPTURED_AT,
)


class FakeScheduler:
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
    ) -> OperatorSchedulerView:
        self.calls.append(
            captured_at
        )

        return SCHEDULER_VIEW


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
        trading_date: date,
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
    scheduler: FakeScheduler,
) -> OperatorTransportService:
    return OperatorTransportService(
        status=UnusedStatus(),
        strategy=UnusedStrategy(),
        notifications=UnusedNotifications(),
        scheduler=scheduler,
        reporting=UnusedReporting(),
        control=UnusedControl(),
    )


def test_scheduler_transport_preserves_exact_owner() -> None:
    scheduler = FakeScheduler()

    transport = make_transport(
        scheduler
    )

    assert (
        transport.scheduler
        is scheduler
    )


def test_scheduler_transport_delegates_once() -> None:
    scheduler = FakeScheduler()

    transport = make_transport(
        scheduler
    )

    result = transport.get_scheduler(
        OperatorSchedulerRequest(
            captured_at=CAPTURED_AT,
        )
    )

    assert result is SCHEDULER_VIEW

    assert scheduler.calls == [
        CAPTURED_AT,
    ]


def test_scheduler_transport_rejects_wrong_request() -> None:
    transport = make_transport(
        FakeScheduler()
    )

    with pytest.raises(
        TypeError,
        match="OperatorSchedulerRequest",
    ):
        transport.get_scheduler(
            object(),  # type: ignore[arg-type]
        )


def test_scheduler_http_uses_public_asgi_contract() -> None:
    scheduler = FakeScheduler()

    transport = make_transport(
        scheduler
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

    async def request_scheduler(
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
                    "scheduler"
                ),
                "raw_path": (
                    b"/api/v1/operator/"
                    b"scheduler"
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
        request_scheduler()
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

    assert scheduler.calls == [
        CAPTURED_AT,
    ]

    assert (
        payload["state"]
        == "MONITORING"
    )

    assert (
        payload["trading_date"]
        == "2026-08-31"
    )

    assert (
        payload["can_accept_new_entries"]
        is True
    )

    assert (
        payload["can_manage_positions"]
        is True
    )

    assert (
        payload["is_terminal"]
        is False
    )
