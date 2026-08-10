from datetime import (
    date,
    datetime,
)

import pytest

from src.notifications.end_of_day_notifications import (
    TradingDayEndOfDayNotificationResult,
)
from src.reporting.end_of_day_reporting import (
    TradingDayEndOfDayReportingCoordinator,
)
from src.reporting.reporting_types import (
    DailyTradeAnalyticsSummary,
    DailyTradeReport,
)
from src.services.scheduler import (
    TradingDayCloseReadiness,
    TradingDayEndOfDayResult,
    TradingDaySnapshot,
    TradingDayState,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

STARTED = datetime(
    2026,
    8,
    10,
    9,
    15,
)

EVALUATED = datetime(
    2026,
    8,
    10,
    15,
    20,
)


def closed_notification_result(
) -> TradingDayEndOfDayNotificationResult:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.CLOSED,
        started_at=STARTED,
        closed_at=EVALUATED,
        updated_at=EVALUATED,
    )

    result = TradingDayEndOfDayResult(
        complete=True,
        transitioned_to_closed=False,
        snapshot=snapshot,
        readiness=None,
        evaluated_at=EVALUATED,
    )

    return TradingDayEndOfDayNotificationResult(
        end_of_day_result=result,
        summary_result=None,
    )


def incomplete_notification_result(
) -> TradingDayEndOfDayNotificationResult:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.EXIT_ONLY,
        started_at=STARTED,
        updated_at=EVALUATED,
    )

    result = TradingDayEndOfDayResult(
        complete=False,
        transitioned_to_closed=False,
        snapshot=snapshot,
        readiness=TradingDayCloseReadiness(
            open_position_count=1,
            unresolved_order_count=0,
        ),
        evaluated_at=EVALUATED,
    )

    return TradingDayEndOfDayNotificationResult(
        end_of_day_result=result,
        summary_result=None,
    )


def empty_daily_report(
    *,
    trading_date: date = TRADING_DATE,
) -> DailyTradeReport:
    analytics = DailyTradeAnalyticsSummary(
        trading_date=trading_date,
        runtime_count=0,
        recovered_runtime_count=0,
        failed_runtime_count=0,
        position_count=0,
        open_position_count=0,
        closed_position_count=0,
        winning_position_count=0,
        losing_position_count=0,
        breakeven_position_count=0,
        realized_pnl=0.0,
        gross_profit=0.0,
        gross_loss=0.0,
        average_closed_position_pnl=0.0,
        average_win=0.0,
        average_loss=0.0,
        largest_win=0.0,
        largest_loss=0.0,
        win_rate_percent=0.0,
        profit_factor=None,
        total_original_quantity=0,
        total_closed_quantity=0,
        total_exit_filled_quantity=0,
        exit_persistence_mismatch_count=0,
        audit_event_count=0,
        calculated_at=EVALUATED,
    )

    return DailyTradeReport(
        trading_date=trading_date,
        runtime_reports=(),
        analytics=analytics,
        generated_at=EVALUATED,
    )


class FakeEndOfDay:
    def __init__(
        self,
        *,
        result:
            TradingDayEndOfDayNotificationResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[datetime] = []

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayEndOfDayNotificationResult:
        self.calls.append(
            evaluated_at
        )

        if self.error is not None:
            raise self.error

        if self.result is None:
            raise RuntimeError(
                "fake EOD has no result"
            )

        return self.result


class FakeDailyReport:
    def __init__(
        self,
        *,
        report: DailyTradeReport | None = None,
        error: Exception | None = None,
    ) -> None:
        self.report = report
        self.error = error

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

        if self.error is not None:
            raise self.error

        if self.report is None:
            raise RuntimeError(
                "fake daily report has no report"
            )

        return self.report


def test_incomplete_eod_does_not_generate_report():
    end_of_day = FakeEndOfDay(
        result=incomplete_notification_result()
    )

    daily_report = FakeDailyReport(
        report=empty_daily_report()
    )

    result = (
        TradingDayEndOfDayReportingCoordinator(
            end_of_day=end_of_day,
            daily_report=daily_report,
        )
        .evaluate(
            evaluated_at=EVALUATED
        )
    )

    assert result.report_attempted is False
    assert result.report_successful is False
    assert result.report is None
    assert result.report_error is None

    assert daily_report.calls == []


def test_complete_eod_generates_report_from_m10_trading_date():
    upstream = closed_notification_result()

    end_of_day = FakeEndOfDay(
        result=upstream
    )

    report = empty_daily_report()

    daily_report = FakeDailyReport(
        report=report
    )

    result = (
        TradingDayEndOfDayReportingCoordinator(
            end_of_day=end_of_day,
            daily_report=daily_report,
        )
        .evaluate(
            evaluated_at=EVALUATED
        )
    )

    assert (
        result.notification_result
        is upstream
    )

    assert result.report is report
    assert result.report_error is None
    assert result.report_attempted is True
    assert result.report_successful is True

    assert daily_report.calls == [
        (
            TRADING_DATE,
            EVALUATED,
        )
    ]


def test_reporting_failure_does_not_change_upstream_result():
    upstream = closed_notification_result()

    daily_report = FakeDailyReport(
        error=RuntimeError(
            "report database unavailable"
        )
    )

    result = (
        TradingDayEndOfDayReportingCoordinator(
            end_of_day=FakeEndOfDay(
                result=upstream
            ),
            daily_report=daily_report,
        )
        .evaluate(
            evaluated_at=EVALUATED
        )
    )

    assert (
        result.notification_result
        is upstream
    )

    assert (
        result.notification_result
        .end_of_day_result
        .complete
        is True
    )

    assert result.report is None
    assert result.report_attempted is True
    assert result.report_successful is False

    assert result.report_error is not None

    assert (
        "report database unavailable"
        in result.report_error
    )


def test_upstream_eod_exception_propagates_unchanged():
    original = RuntimeError(
        "authoritative EOD failed"
    )

    end_of_day = FakeEndOfDay(
        error=original
    )

    daily_report = FakeDailyReport(
        report=empty_daily_report()
    )

    coordinator = (
        TradingDayEndOfDayReportingCoordinator(
            end_of_day=end_of_day,
            daily_report=daily_report,
        )
    )

    with pytest.raises(
        RuntimeError,
        match="authoritative EOD failed",
    ) as captured:
        coordinator.evaluate(
            evaluated_at=EVALUATED
        )

    assert captured.value is original

    assert daily_report.calls == []


def test_mismatched_daily_report_date_is_isolated():
    wrong_date = date(
        2026,
        8,
        11,
    )

    result = (
        TradingDayEndOfDayReportingCoordinator(
            end_of_day=FakeEndOfDay(
                result=(
                    closed_notification_result()
                )
            ),
            daily_report=FakeDailyReport(
                report=empty_daily_report(
                    trading_date=wrong_date
                )
            ),
        )
        .evaluate(
            evaluated_at=EVALUATED
        )
    )

    assert result.report is None
    assert result.report_error is not None

    assert (
        "authoritative M10 snapshot"
        in result.report_error
    )
