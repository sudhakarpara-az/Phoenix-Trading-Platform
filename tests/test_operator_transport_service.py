from __future__ import annotations

from datetime import date
from datetime import datetime
from typing import cast

import pytest

from src.api.operator_control import (
    OperatorControlStateView,
    OperatorExitAndStopView,
)
from src.api.operator_status import (
    OperatorStatusView,
)
from src.api.operator_transport import (
    OperatorDailyReportRequest,
    OperatorExitAndStopRequest,
    OperatorResumeRequest,
    OperatorRuntimeReportRequest,
    OperatorStatusRequest,
    OperatorTransportService,
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
    object(),
)

EXIT_RESULT = cast(
    OperatorExitAndStopView,
    object(),
)

RESUME_RESULT = cast(
    OperatorControlStateView,
    object(),
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


class FakeStatus:
    def __init__(
        self,
    ) -> None:
        self.calls = 0
        self.captured_at: (
            datetime | None
        ) = None

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorStatusView:
        self.calls += 1
        self.captured_at = captured_at
        return STATUS_RESULT


class FakeReporting:
    def __init__(
        self,
    ) -> None:
        self.runtime_calls = 0
        self.daily_calls = 0

        self.runtime_args = None
        self.daily_args = None

    def current_runtime_json(
        self,
        *,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        self.runtime_calls += 1

        self.runtime_args = (
            generated_at,
            indent,
        )

        return '{"kind":"runtime"}'

    def daily_trade_json(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        self.daily_calls += 1

        self.daily_args = (
            trading_date,
            generated_at,
            indent,
        )

        return '{"kind":"daily"}'


class FakeStrategy:
    def capture(
        self,
        *,
        captured_at,
    ):
        raise AssertionError(
            "legacy transport tests must not "
            "invoke strategy projection"
        )


class FakeNotifications:
    def capture(
        self,
        *,
        captured_at,
    ):
        raise AssertionError(
            "legacy transport tests must not "
            "invoke notifications"
        )


class FakeScheduler:
    def capture(
        self,
        *,
        captured_at,
    ):
        raise AssertionError(
            "scheduler must not be called"
        )


class FakeControl:
    def __init__(
        self,
    ) -> None:
        self.exit_calls = 0
        self.resume_calls = 0

        self.exit_args = None
        self.resume_args = None

    def exit_and_stop(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> OperatorExitAndStopView:
        self.exit_calls += 1

        self.exit_args = (
            requested_at,
            message,
        )

        return EXIT_RESULT

    def resume(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> OperatorControlStateView:
        self.resume_calls += 1

        self.resume_args = (
            requested_at,
            message,
        )

        return RESUME_RESULT


def make_service():
    status = FakeStatus()
    reporting = FakeReporting()
    control = FakeControl()

    service = OperatorTransportService(
        status=status,
        strategy=FakeStrategy(),
        notifications=FakeNotifications(),
        scheduler=FakeScheduler(),
        positions=_UnusedPositions(),
        orders=_UnusedOrders(),
        reporting=reporting,
        control=control,
    )

    return (
        service,
        status,
        reporting,
        control,
    )


def test_constructor_preserves_exact_services() -> None:
    (
        service,
        status,
        reporting,
        control,
    ) = make_service()

    assert service.status is status
    assert service.reporting is reporting
    assert service.control is control


def test_status_request_delegates_exactly_once() -> None:
    (
        service,
        status,
        _,
        _,
    ) = make_service()

    result = service.get_status(
        OperatorStatusRequest(
            captured_at=NOW,
        )
    )

    assert result is STATUS_RESULT
    assert status.calls == 1
    assert status.captured_at == NOW


def test_runtime_report_request_delegates_exactly_once() -> None:
    (
        service,
        _,
        reporting,
        _,
    ) = make_service()

    result = (
        service
        .get_current_runtime_report(
            OperatorRuntimeReportRequest(
                generated_at=NOW,
                indent=2,
            )
        )
    )

    assert result == '{"kind":"runtime"}'
    assert reporting.runtime_calls == 1

    assert reporting.runtime_args == (
        NOW,
        2,
    )


def test_daily_report_request_delegates_exactly_once() -> None:
    (
        service,
        _,
        reporting,
        _,
    ) = make_service()

    result = (
        service
        .get_daily_trade_report(
            OperatorDailyReportRequest(
                trading_date=DAY,
                generated_at=NOW,
                indent=None,
            )
        )
    )

    assert result == '{"kind":"daily"}'
    assert reporting.daily_calls == 1

    assert reporting.daily_args == (
        DAY,
        NOW,
        None,
    )


def test_exit_and_stop_delegates_exactly_once() -> None:
    (
        service,
        _,
        _,
        control,
    ) = make_service()

    result = service.exit_and_stop(
        OperatorExitAndStopRequest(
            requested_at=NOW,
            message="operator stop",
        )
    )

    assert result is EXIT_RESULT
    assert control.exit_calls == 1

    assert control.exit_args == (
        NOW,
        "operator stop",
    )


def test_resume_delegates_exactly_once() -> None:
    (
        service,
        _,
        _,
        control,
    ) = make_service()

    result = service.resume(
        OperatorResumeRequest(
            requested_at=NOW,
            message="operator resume",
        )
    )

    assert result is RESUME_RESULT
    assert control.resume_calls == 1

    assert control.resume_args == (
        NOW,
        "operator resume",
    )


def test_request_contracts_reject_wrong_types() -> None:
    with pytest.raises(
        TypeError,
        match="captured_at must be datetime",
    ):
        OperatorStatusRequest(
            captured_at="bad",  # type: ignore[arg-type]
        )

    with pytest.raises(
        TypeError,
        match="generated_at must be datetime",
    ):
        OperatorRuntimeReportRequest(
            generated_at="bad",  # type: ignore[arg-type]
        )

    with pytest.raises(
        TypeError,
        match="trading_date must be date",
    ):
        OperatorDailyReportRequest(
            trading_date=NOW,  # type: ignore[arg-type]
            generated_at=NOW,
        )

    with pytest.raises(
        TypeError,
        match="message must be str or None",
    ):
        OperatorExitAndStopRequest(
            requested_at=NOW,
            message=123,  # type: ignore[arg-type]
        )


def test_transport_methods_reject_wrong_request_classes() -> None:
    (
        service,
        status,
        reporting,
        control,
    ) = make_service()

    with pytest.raises(
        TypeError,
        match="OperatorStatusRequest",
    ):
        service.get_status(
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(
        TypeError,
        match="OperatorRuntimeReportRequest",
    ):
        service.get_current_runtime_report(
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(
        TypeError,
        match="OperatorDailyReportRequest",
    ):
        service.get_daily_trade_report(
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(
        TypeError,
        match="OperatorExitAndStopRequest",
    ):
        service.exit_and_stop(
            object(),  # type: ignore[arg-type]
        )

    with pytest.raises(
        TypeError,
        match="OperatorResumeRequest",
    ):
        service.resume(
            object(),  # type: ignore[arg-type]
        )

    assert status.calls == 0
    assert reporting.runtime_calls == 0
    assert reporting.daily_calls == 0
    assert control.exit_calls == 0
    assert control.resume_calls == 0
