"""
Transport-neutral M13 operator contract.

This module defines request DTOs and one thin application facade
over the existing M13 operator services.

It deliberately owns no:

    HTTP framework
    route
    HTTP status code
    authentication / RBAC
    broker operation
    repository
    registry
    execution workflow
    trading policy

Existing M13 safe views remain the response contracts.
M12 remains the owner of report JSON serialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol

from src.api.operator_control import (
    OperatorControlStateView,
    OperatorExitAndStopView,
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
from src.api.operator_status import (
    OperatorStatusView,
)


def _require_datetime(
    value: datetime,
    *,
    name: str,
) -> None:
    if type(value) is not datetime:
        raise TypeError(
            f"{name} must be datetime"
        )


def _require_date(
    value: date,
    *,
    name: str,
) -> None:
    if type(value) is not date:
        raise TypeError(
            f"{name} must be date"
        )


def _require_message(
    value: str | None,
) -> None:
    if (
        value is not None
        and type(value) is not str
    ):
        raise TypeError(
            "message must be str or None"
        )


def _require_indent(
    value: int | None,
) -> None:
    if (
        value is not None
        and type(value) is not int
    ):
        raise TypeError(
            "indent must be int or None"
        )


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorStatusRequest:
    captured_at: datetime

    def __post_init__(
        self,
    ) -> None:
        _require_datetime(
            self.captured_at,
            name="captured_at",
        )


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorStrategyRequest:
    captured_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorNotificationRequest:
    captured_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorSchedulerRequest:
    captured_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorPositionsRequest:
    captured_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorOrdersRequest:
    captured_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorRuntimeReportRequest:
    generated_at: datetime
    indent: int | None = None

    def __post_init__(
        self,
    ) -> None:
        _require_datetime(
            self.generated_at,
            name="generated_at",
        )

        _require_indent(
            self.indent
        )


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorDailyReportRequest:
    trading_date: date
    generated_at: datetime
    indent: int | None = None

    def __post_init__(
        self,
    ) -> None:
        _require_date(
            self.trading_date,
            name="trading_date",
        )

        _require_datetime(
            self.generated_at,
            name="generated_at",
        )

        _require_indent(
            self.indent
        )


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorExitAndStopRequest:
    requested_at: datetime
    message: str | None = None

    def __post_init__(
        self,
    ) -> None:
        _require_datetime(
            self.requested_at,
            name="requested_at",
        )

        _require_message(
            self.message
        )


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorResumeRequest:
    requested_at: datetime
    message: str | None = None

    def __post_init__(
        self,
    ) -> None:
        _require_datetime(
            self.requested_at,
            name="requested_at",
        )

        _require_message(
            self.message
        )


class OperatorStatusTransportPort(
    Protocol,
):
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorStatusView:
        ...



class OperatorStrategyTransportPort(
    Protocol
):
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorStrategyView:
        ...


class OperatorNotificationTransportPort(
    Protocol,
):
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorNotificationView:
        ...


class OperatorSchedulerTransportPort(
    Protocol,
):
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorSchedulerView:
        ...


class OperatorPositionsTransportPort(
    Protocol,
):
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorPositionsView:
        ...


class OperatorOrdersTransportPort(
    Protocol,
):
    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorOrdersView:
        ...


class OperatorReportingTransportPort(
    Protocol,
):
    def current_runtime_json(
        self,
        *,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        ...

    def daily_trade_json(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        ...


class OperatorControlTransportPort(
    Protocol,
):
    def exit_and_stop(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> OperatorExitAndStopView:
        ...

    def resume(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> OperatorControlStateView:
        ...


class OperatorTransportService:
    """
    Thin M13 transport-independent application facade.

    Every method delegates exactly once to an already-composed
    authoritative M13 service.
    """

    def __init__(
        self,
        *,
        status: OperatorStatusTransportPort,
        strategy: OperatorStrategyTransportPort,
        notifications: OperatorNotificationTransportPort,
        scheduler: OperatorSchedulerTransportPort,
        positions: OperatorPositionsTransportPort,
        orders: OperatorOrdersTransportPort,
        reporting: OperatorReportingTransportPort,
        control: OperatorControlTransportPort,
    ) -> None:
        self._status = status
        self._strategy = strategy
        self._notifications = notifications
        self._scheduler = scheduler
        self._positions = positions
        self._orders = orders
        self._reporting = reporting
        self._control = control

    @property
    def status(
        self,
    ) -> OperatorStatusTransportPort:
        return self._status


    @property
    def strategy(
        self,
    ) -> OperatorStrategyTransportPort:
        return self._strategy

    @property
    def notifications(
        self,
    ) -> OperatorNotificationTransportPort:
        return self._notifications

    @property
    def scheduler(
        self,
    ) -> OperatorSchedulerTransportPort:
        return self._scheduler

    @property
    def positions(
        self,
    ) -> OperatorPositionsTransportPort:
        return self._positions

    @property
    def orders(
        self,
    ) -> OperatorOrdersTransportPort:
        return self._orders

    @property
    def reporting(
        self,
    ) -> OperatorReportingTransportPort:
        return self._reporting

    @property
    def control(
        self,
    ) -> OperatorControlTransportPort:
        return self._control

    def get_status(
        self,
        request: OperatorStatusRequest,
    ) -> OperatorStatusView:
        if not isinstance(
            request,
            OperatorStatusRequest,
        ):
            raise TypeError(
                "request must be OperatorStatusRequest"
            )

        return self._status.capture(
            captured_at=request.captured_at,
        )


    def get_strategy(
        self,
        request: OperatorStrategyRequest,
    ) -> OperatorStrategyView:
        if not isinstance(
            request,
            OperatorStrategyRequest,
        ):
            raise TypeError(
                "request must be "
                "OperatorStrategyRequest"
            )

        return self._strategy.capture(
            captured_at=request.captured_at,
        )

    def get_notifications(
        self,
        request: OperatorNotificationRequest,
    ) -> OperatorNotificationView:
        if not isinstance(
            request,
            OperatorNotificationRequest,
        ):
            raise TypeError(
                "request must be "
                "OperatorNotificationRequest"
            )

        return self._notifications.capture(
            captured_at=request.captured_at,
        )

    def get_scheduler(
        self,
        request: OperatorSchedulerRequest,
    ) -> OperatorSchedulerView:
        if not isinstance(
            request,
            OperatorSchedulerRequest,
        ):
            raise TypeError(
                "request must be "
                "OperatorSchedulerRequest"
            )

        return self._scheduler.capture(
            captured_at=request.captured_at,
        )

    def get_positions(
        self,
        request: OperatorPositionsRequest,
    ) -> OperatorPositionsView:
        if not isinstance(
            request,
            OperatorPositionsRequest,
        ):
            raise TypeError(
                "request must be "
                "OperatorPositionsRequest"
            )

        return self._positions.capture(
            captured_at=request.captured_at,
        )

    def get_orders(
        self,
        request: OperatorOrdersRequest,
    ) -> OperatorOrdersView:
        if not isinstance(
            request,
            OperatorOrdersRequest,
        ):
            raise TypeError(
                "request must be "
                "OperatorOrdersRequest"
            )

        return self._orders.capture(
            captured_at=request.captured_at,
        )

    def get_current_runtime_report(
        self,
        request: OperatorRuntimeReportRequest,
    ) -> str:
        if not isinstance(
            request,
            OperatorRuntimeReportRequest,
        ):
            raise TypeError(
                "request must be "
                "OperatorRuntimeReportRequest"
            )

        return (
            self._reporting
            .current_runtime_json(
                generated_at=(
                    request.generated_at
                ),
                indent=request.indent,
            )
        )

    def get_daily_trade_report(
        self,
        request: OperatorDailyReportRequest,
    ) -> str:
        if not isinstance(
            request,
            OperatorDailyReportRequest,
        ):
            raise TypeError(
                "request must be "
                "OperatorDailyReportRequest"
            )

        return (
            self._reporting
            .daily_trade_json(
                trading_date=(
                    request.trading_date
                ),
                generated_at=(
                    request.generated_at
                ),
                indent=request.indent,
            )
        )

    def exit_and_stop(
        self,
        request: OperatorExitAndStopRequest,
    ) -> OperatorExitAndStopView:
        if not isinstance(
            request,
            OperatorExitAndStopRequest,
        ):
            raise TypeError(
                "request must be "
                "OperatorExitAndStopRequest"
            )

        return self._control.exit_and_stop(
            requested_at=request.requested_at,
            message=request.message,
        )

    def resume(
        self,
        request: OperatorResumeRequest,
    ) -> OperatorControlStateView:
        if not isinstance(
            request,
            OperatorResumeRequest,
        ):
            raise TypeError(
                "request must be OperatorResumeRequest"
            )

        return self._control.resume(
            requested_at=request.requested_at,
            message=request.message,
        )


__all__ = [
    "OperatorControlTransportPort",
    "OperatorDailyReportRequest",
    "OperatorExitAndStopRequest",
    "OperatorReportingTransportPort",
    "OperatorResumeRequest",
    "OperatorRuntimeReportRequest",
    "OperatorStatusRequest",
    "OperatorStatusTransportPort",
    "OperatorTransportService",
    "OperatorStrategyRequest",
    "OperatorStrategyTransportPort",
    "OperatorNotificationRequest",
    "OperatorNotificationTransportPort",
    "OperatorSchedulerRequest",
    "OperatorSchedulerTransportPort",
    "OperatorPositionsRequest",
    "OperatorPositionsTransportPort",
    "OperatorOrdersRequest",
    "OperatorOrdersTransportPort",
]
