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
from src.api.operator_notifications import (
    OperatorNotificationQueueView,
    OperatorNotificationSummaryView,
    OperatorNotificationView,
)
from src.api.operator_transport import (
    OperatorNotificationRequest,
    OperatorTransportService,
)


CAPTURED_AT = datetime(
    2026,
    8,
    31,
    12,
    15,
)


NOTIFICATION_VIEW = (
    OperatorNotificationView(
        summary=(
            OperatorNotificationSummaryView(
                runtime_id="RUNTIME-1",
                total_count=12,
                info_count=5,
                warning_count=3,
                error_count=2,
                critical_count=2,
                runtime_count=2,
                trade_count=3,
                risk_count=2,
                recovery_count=1,
                health_count=3,
                summary_count=1,
                first_event_at=datetime(
                    2026,
                    8,
                    31,
                    9,
                    20,
                ),
                last_event_at=datetime(
                    2026,
                    8,
                    31,
                    12,
                    10,
                ),
                captured_at=CAPTURED_AT,
            )
        ),
        queue=(
            OperatorNotificationQueueView(
                started=True,
                accepting=True,
                capacity=256,
                pending_count=4,
                delivered_count=100,
                failed_delivery_count=3,
                dropped_count=2,
                lifecycle_failure_count=1,
                last_lifecycle_error=(
                    "worker restart"
                ),
                captured_at=CAPTURED_AT,
            )
        ),
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


class _UnusedPositions:
    def capture(
        self,
        *,
        captured_at,
    ):
        raise AssertionError(
            "positions must not be called"
        )


class FakeNotifications:
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
    ) -> OperatorNotificationView:
        self.calls.append(
            captured_at
        )

        return NOTIFICATION_VIEW


class UnusedStatus:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError(
            "status must not be called"
        )


class UnusedStrategy:
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> Any:
        raise AssertionError(
            "strategy must not be called"
        )


class UnusedReporting:
    def current_runtime_json(
        self,
        *,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        raise AssertionError(
            "runtime reporting must not be called"
        )

    def daily_trade_json(
        self,
        *,
        trading_date: Any,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        raise AssertionError(
            "daily reporting must not be called"
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
            "control writes must not be called"
        )

    def resume(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> Any:
        raise AssertionError(
            "control writes must not be called"
        )


def make_transport(
    notifications: FakeNotifications,
) -> OperatorTransportService:
    return OperatorTransportService(
        status=UnusedStatus(),
        strategy=UnusedStrategy(),
        notifications=notifications,
        scheduler=UnusedScheduler(),
        positions=_UnusedPositions(),
        orders=_UnusedOrders(),
        reporting=UnusedReporting(),
        control=UnusedControl(),
    )


def test_transport_preserves_exact_notification_owner() -> None:
    notifications = FakeNotifications()

    transport = make_transport(
        notifications
    )

    assert (
        transport.notifications
        is notifications
    )


def test_notification_read_delegates_exactly_once() -> None:
    notifications = FakeNotifications()

    transport = make_transport(
        notifications
    )

    result = transport.get_notifications(
        OperatorNotificationRequest(
            captured_at=CAPTURED_AT,
        )
    )

    assert (
        result
        is NOTIFICATION_VIEW
    )

    assert notifications.calls == [
        CAPTURED_AT,
    ]


def test_notification_read_rejects_wrong_request() -> None:
    transport = make_transport(
        FakeNotifications()
    )

    with pytest.raises(
        TypeError,
        match="OperatorNotificationRequest",
    ):
        transport.get_notifications(
            object(),  # type: ignore[arg-type]
        )


def test_http_notification_route_uses_public_asgi_contract() -> None:
    notifications = FakeNotifications()

    transport = make_transport(
        notifications
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

    async def request_notifications(
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
                    "notifications"
                ),
                "raw_path": (
                    b"/api/v1/operator/"
                    b"notifications"
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
        request_notifications()
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
        response_start.get(
            "status"
        )
        == 200
    )

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

    assert notifications.calls == [
        CAPTURED_AT,
    ]

    assert (
        payload["summary"]["runtime_id"]
        == "RUNTIME-1"
    )

    assert (
        payload["summary"]["total_count"]
        == 12
    )

    assert (
        payload["summary"]["warning_count"]
        == 3
    )

    assert (
        payload["summary"]["critical_count"]
        == 2
    )

    assert (
        payload["summary"]["risk_count"]
        == 2
    )

    assert (
        payload["summary"]["health_count"]
        == 3
    )

    assert payload["queue"] is not None

    assert (
        payload["queue"]["started"]
        is True
    )

    assert (
        payload["queue"]["accepting"]
        is True
    )

    assert (
        payload["queue"]["capacity"]
        == 256
    )

    assert (
        payload["queue"]["pending_count"]
        == 4
    )

    assert (
        payload["queue"]["delivered_count"]
        == 100
    )

    assert (
        payload["queue"]["failed_delivery_count"]
        == 3
    )

    assert (
        payload["queue"]["dropped_count"]
        == 2
    )

    assert (
        payload["queue"]["lifecycle_failure_count"]
        == 1
    )

    assert (
        payload["queue"]["last_lifecycle_error"]
        == "worker restart"
    )
