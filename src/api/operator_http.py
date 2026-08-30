"""
FastAPI adapter for the M13 operator read surface.

This module is the framework-specific edge around the existing
transport-neutral OperatorTransportService contract.

The adapter deliberately owns no broker, persistence, registry,
execution, risk, strategy, or trading-control implementation.

Only read routes are registered in this foundation slice.
Application/server lifecycle is composed separately.
"""

from __future__ import annotations

from datetime import date
from datetime import datetime
from typing import Annotated
from typing import Callable
from typing import Protocol

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import Query
from fastapi.responses import Response

from src.api.operator_status import (
    OperatorStatusView,
)
from src.api.operator_strategy import (
    OperatorStrategyView,
)
from src.api.operator_notifications import (
    OperatorNotificationView,
)
from src.api.operator_scheduler import (
    OperatorSchedulerView,
)
from src.api.operator_positions import (
    OperatorPositionsView,
)
from src.api.operator_orders import (
    OperatorOrdersView,
)
from src.api.operator_transport import (
    OperatorDailyReportRequest,
    OperatorRuntimeReportRequest,
    OperatorStatusRequest,
    OperatorStrategyRequest,
    OperatorNotificationRequest,
    OperatorSchedulerRequest,
    OperatorPositionsRequest,
    OperatorOrdersRequest,
)


OperatorHttpClock = Callable[
    [],
    datetime,
]

OperatorHttpApplication = FastAPI


class OperatorHttpTransportPort(
    Protocol,
):
    def get_status(
        self,
        request: OperatorStatusRequest,
    ) -> OperatorStatusView:
        ...


    def get_strategy(
        self,
        request: OperatorStrategyRequest,
    ) -> OperatorStrategyView:
        ...

    def get_notifications(
        self,
        request: OperatorNotificationRequest,
    ) -> OperatorNotificationView:
        ...

    def get_scheduler(
        self,
        request: OperatorSchedulerRequest,
    ) -> OperatorSchedulerView:
        ...

    def get_positions(
        self,
        request: OperatorPositionsRequest,
    ) -> OperatorPositionsView:
        ...

    def get_orders(
        self,
        request: OperatorOrdersRequest,
    ) -> OperatorOrdersView:
        ...

    def get_current_runtime_report(
        self,
        request: OperatorRuntimeReportRequest,
    ) -> str:
        ...

    def get_daily_trade_report(
        self,
        request: OperatorDailyReportRequest,
    ) -> str:
        ...


class OperatorHttpAdapter:
    """
    Thin read-only FastAPI adapter over the existing M13
    transport-neutral service boundary.
    """

    def __init__(
        self,
        *,
        transport: OperatorHttpTransportPort,
        clock: OperatorHttpClock,
    ) -> None:
        self._transport = transport
        self._clock = clock

    @property
    def transport(
        self,
    ) -> OperatorHttpTransportPort:
        return self._transport

    @property
    def clock(
        self,
    ) -> OperatorHttpClock:
        return self._clock

    def build_app(
        self,
    ) -> OperatorHttpApplication:
        """
        Build one passive FastAPI application.

        No server is started here.
        """

        app = FastAPI(
            title="Phoenix Operator API",
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )

        router = APIRouter(
            prefix="/api/v1/operator",
        )

        @router.get(
            "/status",
            response_model=None,
        )
        def get_operator_status(
        ) -> OperatorStatusView:
            captured_at = self._read_clock()

            return self._transport.get_status(
                OperatorStatusRequest(
                    captured_at=captured_at,
                )
            )


        @router.get(
            "/strategy",
            response_model=None,
        )
        def get_operator_strategy(
        ) -> OperatorStrategyView:
            captured_at = self._read_clock()

            return self._transport.get_strategy(
                OperatorStrategyRequest(
                    captured_at=captured_at,
                )
            )

        @router.get(
            "/notifications",
            response_model=None,
        )
        def get_operator_notifications(
        ) -> OperatorNotificationView:
            captured_at = self._read_clock()

            return self._transport.get_notifications(
                OperatorNotificationRequest(
                    captured_at=captured_at,
                )
            )

        @router.get(
            "/scheduler",
            response_model=None,
        )
        def get_operator_scheduler(
        ) -> OperatorSchedulerView:
            captured_at = self._read_clock()

            return self._transport.get_scheduler(
                OperatorSchedulerRequest(
                    captured_at=captured_at,
                )
            )

        @router.get(
            "/positions",
            response_model=None,
        )
        def get_operator_positions(
        ) -> OperatorPositionsView:
            captured_at = self._read_clock()

            return self._transport.get_positions(
                OperatorPositionsRequest(
                    captured_at=captured_at,
                )
            )

        @router.get(
            "/orders",
            response_model=None,
        )
        def get_operator_orders(
        ) -> OperatorOrdersView:
            captured_at = self._read_clock()

            return self._transport.get_orders(
                OperatorOrdersRequest(
                    captured_at=captured_at,
                )
            )

        @router.get(
            "/reports/runtime",
            response_class=Response,
        )
        def get_runtime_report(
        ) -> Response:
            generated_at = self._read_clock()

            payload = (
                self._transport
                .get_current_runtime_report(
                    OperatorRuntimeReportRequest(
                        generated_at=generated_at,
                    )
                )
            )

            return Response(
                content=payload,
                media_type="application/json",
            )

        @router.get(
            "/reports/daily",
            response_class=Response,
        )
        def get_daily_report(
            trading_date: Annotated[
                date,
                Query(),
            ],
        ) -> Response:
            generated_at = self._read_clock()

            payload = (
                self._transport
                .get_daily_trade_report(
                    OperatorDailyReportRequest(
                        trading_date=trading_date,
                        generated_at=generated_at,
                    )
                )
            )

            return Response(
                content=payload,
                media_type="application/json",
            )

        app.include_router(
            router
        )

        return app

    def _read_clock(
        self,
    ) -> datetime:
        value = self._clock()

        if type(value) is not datetime:
            raise TypeError(
                "operator HTTP clock must return datetime"
            )

        return value


def build_operator_http_app(
    *,
    transport: OperatorHttpTransportPort,
    clock: OperatorHttpClock,
) -> OperatorHttpApplication:
    """
    Construct the passive read-only FastAPI application.

    The function does not start Uvicorn or mutate runtime state.
    """

    return OperatorHttpAdapter(
        transport=transport,
        clock=clock,
    ).build_app()


__all__ = [
    "OperatorHttpApplication",
    "OperatorHttpAdapter",
    "OperatorHttpClock",
    "OperatorHttpTransportPort",
    "build_operator_http_app",
]
