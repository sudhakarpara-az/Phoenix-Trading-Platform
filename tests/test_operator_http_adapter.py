from __future__ import annotations

import asyncio
from datetime import date
from datetime import datetime
from typing import Any
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from src.api.operator_http import (
    OperatorHttpAdapter,
    build_operator_http_app,
)
from src.api.operator_status import (
    OperatorStatusView,
)
from src.api.operator_transport import (
    OperatorDailyReportRequest,
    OperatorRuntimeReportRequest,
    OperatorStatusRequest,
)


NOW = datetime(
    2026,
    8,
    30,
    9,
    0,
)

DAY = date(
    2026,
    8,
    30,
)


STATUS_RESULT = cast(
    OperatorStatusView,
    {
        "kind": "status",
    },
)


class FakeClock:
    def __init__(
        self,
        value: object = NOW,
    ) -> None:
        self.value = value
        self.calls = 0

    def __call__(
        self,
    ) -> datetime:
        self.calls += 1

        return cast(
            datetime,
            self.value,
        )


class FakeTransport:
    def __init__(
        self,
    ) -> None:
        self.status_calls = 0
        self.runtime_calls = 0
        self.daily_calls = 0

        self.status_request: (
            OperatorStatusRequest | None
        ) = None

        self.runtime_request: (
            OperatorRuntimeReportRequest | None
        ) = None

        self.daily_request: (
            OperatorDailyReportRequest | None
        ) = None

    def get_status(
        self,
        request: OperatorStatusRequest,
    ) -> OperatorStatusView:
        self.status_calls += 1
        self.status_request = request

        return STATUS_RESULT

    def get_strategy(
        self,
        request,
    ):
        raise AssertionError(
            "legacy HTTP tests must not invoke "
            "strategy route"
        )

    def get_scheduler(
        self,
        request,
    ):
        raise AssertionError(
            "scheduler route is covered "
            "by dedicated ASGI test"
        )

    def get_positions(
        self,
        request,
    ):
        raise AssertionError(
            "positions route is covered "
            "by dedicated ASGI test"
        )

    def get_orders(
        self,
        request,
    ):
        raise AssertionError(
            "orders route is covered "
            "by dedicated ASGI test"
        )

    def get_current_runtime_report(
        self,
        request: OperatorRuntimeReportRequest,
    ) -> str:
        self.runtime_calls += 1
        self.runtime_request = request

        return '{"kind":"runtime"}'

    def get_daily_trade_report(
        self,
        request: OperatorDailyReportRequest,
    ) -> str:
        self.daily_calls += 1
        self.daily_request = request

        return '{"kind":"daily"}'

    def get_notifications(
        self,
        request,
    ):
        raise AssertionError(
            "notification behavior is covered "
            "by dedicated ASGI test"
        )


def _openapi_paths(
    app: FastAPI,
) -> dict[str, set[str]]:
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )

    raw_paths = cast(
        dict[
            str,
            dict[str, Any],
        ],
        schema.get(
            "paths",
            {},
        ),
    )

    http_methods = {
        "get",
        "put",
        "post",
        "delete",
        "options",
        "head",
        "patch",
        "trace",
    }

    return {
        path: (
            set(operations)
            & http_methods
        )
        for path, operations in (
            raw_paths.items()
        )
    }


def _request(
    app: FastAPI,
    *,
    method: str,
    path: str,
    query_string: bytes = b"",
) -> tuple[
    int,
    dict[str, str],
    bytes,
]:
    messages: list[
        dict[str, Any]
    ] = []

    async def run() -> None:
        request_sent = False

        async def receive() -> dict[str, Any]:
            nonlocal request_sent

            if not request_sent:
                request_sent = True

                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

            return {
                "type": "http.disconnect",
            }

        async def send(
            message: dict[str, Any],
        ) -> None:
            messages.append(
                message
            )

        scope: dict[
            str,
            Any,
        ] = {
            "type": "http",
            "asgi": {
                "version": "3.0",
                "spec_version": "2.3",
            },
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": (
                path.encode(
                    "ascii"
                )
            ),
            "query_string": query_string,
            "root_path": "",
            "headers": [],
            "client": (
                "test-client",
                50000,
            ),
            "server": (
                "test-server",
                80,
            ),
        }

        await app(
            cast(
                Any,
                scope,
            ),
            cast(
                Any,
                receive,
            ),
            cast(
                Any,
                send,
            ),
        )

    asyncio.run(
        run()
    )

    starts = [
        message
        for message in messages
        if (
            message.get("type")
            == "http.response.start"
        )
    ]

    if len(starts) != 1:
        raise AssertionError(
            "Expected exactly one "
            "http.response.start"
        )

    start = starts[0]

    status = cast(
        int,
        start["status"],
    )

    raw_headers = cast(
        list[
            tuple[
                bytes,
                bytes,
            ]
        ],
        start.get(
            "headers",
            [],
        ),
    )

    headers = {
        key.decode(
            "latin-1"
        ): value.decode(
            "latin-1"
        )
        for key, value
        in raw_headers
    }

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

    return (
        status,
        headers,
        body,
    )


def test_adapter_preserves_exact_dependencies() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    adapter = OperatorHttpAdapter(
        transport=transport,
        clock=clock,
    )

    assert adapter.transport is transport
    assert adapter.clock is clock


def test_app_has_exact_read_only_route_surface() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    app = build_operator_http_app(
        transport=transport,
        clock=clock,
    )

    assert _openapi_paths(
        app
    ) == {'/api/v1/operator/status': {'get'}, '/api/v1/operator/strategy': {'get'}, '/api/v1/operator/scheduler': {'get'}, '/api/v1/operator/positions': {'get'}, '/api/v1/operator/orders': {'get'}, '/api/v1/operator/notifications': {'get'}, '/api/v1/operator/reports/runtime': {'get'}, '/api/v1/operator/reports/daily': {'get'}}

    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_status_route_delegates_once() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    app = build_operator_http_app(
        transport=transport,
        clock=clock,
    )

    (
        status,
        headers,
        body,
    ) = _request(
        app,
        method="GET",
        path=(
            "/api/v1/operator/status"
        ),
    )

    assert status == 200

    assert (
        headers.get(
            "content-type"
        )
        == "application/json"
    )

    assert body == (
        b'{"kind":"status"}'
    )

    assert clock.calls == 1
    assert transport.status_calls == 1

    assert transport.status_request == (
        OperatorStatusRequest(
            captured_at=NOW,
        )
    )

    assert transport.runtime_calls == 0
    assert transport.daily_calls == 0


def test_runtime_report_route_preserves_m12_json() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    app = build_operator_http_app(
        transport=transport,
        clock=clock,
    )

    (
        status,
        headers,
        body,
    ) = _request(
        app,
        method="GET",
        path=(
            "/api/v1/operator/"
            "reports/runtime"
        ),
    )

    assert status == 200

    assert (
        headers.get(
            "content-type"
        )
        == "application/json"
    )

    assert body == (
        b'{"kind":"runtime"}'
    )

    assert clock.calls == 1
    assert transport.runtime_calls == 1

    assert transport.runtime_request == (
        OperatorRuntimeReportRequest(
            generated_at=NOW,
        )
    )

    assert transport.status_calls == 0
    assert transport.daily_calls == 0


def test_daily_report_route_preserves_m12_json() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    app = build_operator_http_app(
        transport=transport,
        clock=clock,
    )

    (
        status,
        headers,
        body,
    ) = _request(
        app,
        method="GET",
        path=(
            "/api/v1/operator/"
            "reports/daily"
        ),
        query_string=(
            b"trading_date=2026-08-30"
        ),
    )

    assert status == 200

    assert (
        headers.get(
            "content-type"
        )
        == "application/json"
    )

    assert body == (
        b'{"kind":"daily"}'
    )

    assert clock.calls == 1
    assert transport.daily_calls == 1

    assert transport.daily_request == (
        OperatorDailyReportRequest(
            trading_date=DAY,
            generated_at=NOW,
        )
    )

    assert transport.status_calls == 0
    assert transport.runtime_calls == 0


def test_invalid_clock_fails_before_transport_read() -> None:
    transport = FakeTransport()

    clock = FakeClock(
        "invalid"
    )

    app = build_operator_http_app(
        transport=transport,
        clock=clock,
    )

    with pytest.raises(
        TypeError,
        match=(
            "operator HTTP clock "
            "must return datetime"
        ),
    ):
        _request(
            app,
            method="GET",
            path=(
                "/api/v1/operator/status"
            ),
        )

    assert clock.calls == 1

    assert transport.status_calls == 0
    assert transport.runtime_calls == 0
    assert transport.daily_calls == 0


def test_no_http_write_routes_are_registered() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    app = build_operator_http_app(
        transport=transport,
        clock=clock,
    )

    for methods in (
        _openapi_paths(
            app
        ).values()
    ):
        assert methods == {
            "get",
        }

    (
        status,
        _,
        _,
    ) = _request(
        app,
        method="POST",
        path=(
            "/api/v1/operator/status"
        ),
    )

    assert status == 405

    assert clock.calls == 0
    assert transport.status_calls == 0
    assert transport.runtime_calls == 0
    assert transport.daily_calls == 0


def test_building_app_is_passive() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    app = build_operator_http_app(
        transport=transport,
        clock=clock,
    )

    assert isinstance(
        app,
        FastAPI,
    )

    assert clock.calls == 0
    assert transport.status_calls == 0
    assert transport.runtime_calls == 0
    assert transport.daily_calls == 0
