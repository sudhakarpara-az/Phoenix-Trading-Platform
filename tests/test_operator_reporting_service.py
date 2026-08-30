from __future__ import annotations

from datetime import (
    date,
    datetime,
)
from typing import cast

import pytest

from src.api.operator_reporting import (
    OperatorReportingService,
)
from src.reporting.reporting_types import (
    DailyTradeReport,
    RuntimeTradeReport,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
    RuntimeSnapshot,
    RuntimeState,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

GENERATED = datetime(
    2026,
    8,
    10,
    15,
    20,
)

STARTED = datetime(
    2026,
    8,
    10,
    9,
    15,
)

UPDATED = datetime(
    2026,
    8,
    10,
    15,
    15,
)


class FakeRuntimeReader:
    def __init__(
        self,
    ) -> None:
        self.read_count = 0

    @property
    def snapshot(
        self,
    ) -> RuntimeSnapshot:
        self.read_count += 1

        return RuntimeSnapshot(
            runtime_id=RuntimeId(
                "M13-REPORT-RUNTIME"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.DRY_RUN,
            state=RuntimeState.RUNNING,
            started_at=STARTED,
            updated_at=UPDATED,
            stopped_at=None,
            failure=None,
            recovery_required=False,
            recovered=False,
        )


class FakeRuntimeReport:
    def __init__(
        self,
        report: RuntimeTradeReport,
    ) -> None:
        self.report = report
        self.calls: list[
            tuple[
                str,
                datetime,
            ]
        ] = []

    def build(
        self,
        *,
        runtime_id: str,
        generated_at: datetime,
    ) -> RuntimeTradeReport:
        self.calls.append(
            (
                runtime_id,
                generated_at,
            )
        )

        return self.report


class FakeDailyReport:
    def __init__(
        self,
        report: DailyTradeReport,
    ) -> None:
        self.report = report
        self.calls: list[
            tuple[
                date,
                datetime,
            ]
        ] = []

    def build(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
    ) -> DailyTradeReport:
        self.calls.append(
            (
                trading_date,
                generated_at,
            )
        )

        return self.report


class FakeSerializer:
    def __init__(
        self,
    ) -> None:
        self.calls: list[
            tuple[
                object,
                int | None,
            ]
        ] = []

    def to_json(
        self,
        report: RuntimeTradeReport | DailyTradeReport,
        *,
        indent: int | None = None,
    ) -> str:
        self.calls.append(
            (
                report,
                indent,
            )
        )

        return "SERIALIZED"


def make_service(
) -> tuple[
    OperatorReportingService,
    FakeRuntimeReader,
    FakeRuntimeReport,
    FakeDailyReport,
    FakeSerializer,
    RuntimeTradeReport,
    DailyTradeReport,
]:
    runtime_value = cast(
        RuntimeTradeReport,
        object(),
    )

    daily_value = cast(
        DailyTradeReport,
        object(),
    )

    runtime = FakeRuntimeReader()

    runtime_report = FakeRuntimeReport(
        runtime_value
    )

    daily_report = FakeDailyReport(
        daily_value
    )

    serializer = FakeSerializer()

    service = OperatorReportingService(
        runtime=runtime,
        runtime_report=runtime_report,
        daily_report=daily_report,
        serializer=serializer,
    )

    return (
        service,
        runtime,
        runtime_report,
        daily_report,
        serializer,
        runtime_value,
        daily_value,
    )


def test_current_runtime_report_uses_authoritative_runtime_id_once():
    (
        service,
        runtime,
        runtime_report,
        _,
        _,
        runtime_value,
        _,
    ) = make_service()

    result = service.current_runtime_report(
        generated_at=GENERATED
    )

    assert result is runtime_value

    assert runtime.read_count == 1

    assert runtime_report.calls == [
        (
            "M13-REPORT-RUNTIME",
            GENERATED,
        )
    ]


def test_daily_report_does_not_read_live_runtime():
    (
        service,
        runtime,
        _,
        daily_report,
        _,
        _,
        daily_value,
    ) = make_service()

    result = service.daily_trade_report(
        trading_date=TRADING_DATE,
        generated_at=GENERATED,
    )

    assert result is daily_value

    assert runtime.read_count == 0

    assert daily_report.calls == [
        (
            TRADING_DATE,
            GENERATED,
        )
    ]


def test_runtime_json_serializes_exact_runtime_report():
    (
        service,
        _,
        _,
        _,
        serializer,
        runtime_value,
        _,
    ) = make_service()

    value = service.current_runtime_json(
        generated_at=GENERATED,
        indent=2,
    )

    assert value == "SERIALIZED"

    assert serializer.calls == [
        (
            runtime_value,
            2,
        )
    ]


def test_daily_json_serializes_exact_daily_report():
    (
        service,
        _,
        _,
        _,
        serializer,
        _,
        daily_value,
    ) = make_service()

    value = service.daily_trade_json(
        trading_date=TRADING_DATE,
        generated_at=GENERATED,
    )

    assert value == "SERIALIZED"

    assert serializer.calls == [
        (
            daily_value,
            None,
        )
    ]


def test_invalid_daily_date_fails_before_report_read():
    (
        service,
        _,
        _,
        daily_report,
        _,
        _,
        _,
    ) = make_service()

    with pytest.raises(
        TypeError,
        match="trading_date must be date",
    ):
        service.daily_trade_report(
            trading_date=GENERATED,  # type: ignore[arg-type]
            generated_at=GENERATED,
        )

    assert daily_report.calls == []
