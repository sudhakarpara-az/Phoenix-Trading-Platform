from __future__ import annotations

from datetime import datetime
from typing import cast

from fastapi import FastAPI
from fastapi.openapi.utils import (
    get_openapi,
)

from src.api.operator_status import (
    OperatorStatusView,
)
from src.api.operator_transport import (
    OperatorDailyReportRequest,
    OperatorRuntimeReportRequest,
    OperatorStatusRequest,
)
from src.app.bootstrap import (
    compose_operator_http_foundation,
)
from src.app.container import (
    PhoenixOperatorApiContainer,
    PhoenixOperatorHttpContainer,
    build_operator_http_foundation,
)


NOW = datetime(
    2026,
    8,
    30,
    9,
    0,
)


class FakeClock:
    def __init__(
        self,
    ) -> None:
        self.calls = 0

    def __call__(
        self,
    ) -> datetime:
        self.calls += 1
        return NOW


class FakeTransport:
    def __init__(
        self,
    ) -> None:
        self.status_calls = 0
        self.runtime_calls = 0
        self.daily_calls = 0

    def get_status(
        self,
        request: OperatorStatusRequest,
    ) -> OperatorStatusView:
        self.status_calls += 1

        return cast(
            OperatorStatusView,
            {
                "kind": "status",
            },
        )

    def get_strategy(
        self,
        request,
    ):
        raise AssertionError(
            "HTTP composition test must not "
            "invoke strategy transport"
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
        return "{}"

    def get_daily_trade_report(
        self,
        request: OperatorDailyReportRequest,
    ) -> str:
        self.daily_calls += 1
        return "{}"

    def get_notifications(
        self,
        request,
    ):
        raise AssertionError(
            "notification behavior is covered "
            "by dedicated ASGI test"
        )


def make_operator_api(
    transport: FakeTransport,
) -> PhoenixOperatorApiContainer:
    operator_api = object.__new__(
        PhoenixOperatorApiContainer
    )

    object.__setattr__(
        operator_api,
        "operator_transport",
        transport,
    )

    return operator_api


def effective_paths(
    app: FastAPI,
) -> dict[str, set[str]]:
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
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
        for path, operations
        in schema.get(
            "paths",
            {},
        ).items()
    }


def test_build_http_foundation_preserves_exact_operator_api() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    operator_api = make_operator_api(
        transport
    )

    result = build_operator_http_foundation(
        operator_api=operator_api,
        clock=clock,
    )

    assert isinstance(
        result,
        PhoenixOperatorHttpContainer,
    )

    assert result.operator_api is operator_api

    assert result.operator_api.operator_transport is transport

    assert isinstance(
        result.app,
        FastAPI,
    )

    assert clock.calls == 0

    assert transport.status_calls == 0
    assert transport.runtime_calls == 0
    assert transport.daily_calls == 0


def test_http_foundation_builds_exact_read_surface() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    result = build_operator_http_foundation(
        operator_api=make_operator_api(
            transport
        ),
        clock=clock,
    )

    assert effective_paths(
        result.app
    ) == {'/api/v1/operator/status': {'get'}, '/api/v1/operator/strategy': {'get'}, '/api/v1/operator/scheduler': {'get'}, '/api/v1/operator/positions': {'get'}, '/api/v1/operator/orders': {'get'}, '/api/v1/operator/notifications': {'get'}, '/api/v1/operator/reports/runtime': {'get'}, '/api/v1/operator/reports/daily': {'get'}}

    assert clock.calls == 0


def test_bootstrap_preserves_exact_operator_api() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    operator_api = make_operator_api(
        transport
    )

    result = compose_operator_http_foundation(
        operator_api=operator_api,
        clock=clock,
    )

    assert result.operator_api is operator_api

    assert (
        result.operator_api
        .operator_transport
        is transport
    )

    assert isinstance(
        result.app,
        FastAPI,
    )


def test_http_composition_is_passive() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    operator_api = make_operator_api(
        transport
    )

    compose_operator_http_foundation(
        operator_api=operator_api,
        clock=clock,
    )

    assert clock.calls == 0
    assert transport.status_calls == 0
    assert transport.runtime_calls == 0
    assert transport.daily_calls == 0


def test_http_composition_exposes_no_write_routes() -> None:
    transport = FakeTransport()
    clock = FakeClock()

    result = compose_operator_http_foundation(
        operator_api=make_operator_api(
            transport
        ),
        clock=clock,
    )

    paths = effective_paths(
        result.app
    )

    assert len(paths) == 8

    for methods in paths.values():
        assert methods == {
            "get",
        }
