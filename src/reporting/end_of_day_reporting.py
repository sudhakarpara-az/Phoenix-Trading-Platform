"""
Phoenix M12 end-of-day reporting boundary.

This module wraps the established M11 EOD notification boundary.

Ordering:

    M10 trading-day close
        -> M11 operational notification handling
            -> M12 durable daily-report projection

Critical invariants:

1. M10 remains authoritative for CLOSED/EXIT_ONLY.
2. M11 notification behavior remains unchanged.
3. M12 reporting runs only when M10 reports complete=True.
4. A reporting failure never changes or masks the upstream
   M10/M11 result.
5. An upstream M10/M11 exception is propagated unchanged.
6. M12 never submits orders, changes positions, publishes runtime
   events, or dispatches notifications from this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    date,
    datetime,
)
from typing import Protocol

from src.notifications.end_of_day_notifications import (
    TradingDayEndOfDayNotificationResult,
)
from src.reporting.reporting_types import (
    DailyTradeReport,
)


class TradingDayEndOfDayNotificationEvaluator(
    Protocol,
):
    """
    Narrow established M11 EOD boundary consumed by M12.
    """

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayEndOfDayNotificationResult:
        ...


class DailyTradeReportBuilder(
    Protocol,
):
    """
    Narrow M12 daily-report projection boundary.
    """

    def build(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
    ) -> DailyTradeReport:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayEndOfDayReportingResult:
    """
    Existing M11 EOD outcome plus optional M12 daily report.

    report_error is informational only. It never changes the
    authoritative trading-day result.
    """

    notification_result: TradingDayEndOfDayNotificationResult

    report: DailyTradeReport | None
    report_error: str | None

    evaluated_at: datetime

    @property
    def report_attempted(
        self,
    ) -> bool:
        return (
            self.notification_result
            .end_of_day_result
            .complete
        )

    @property
    def report_successful(
        self,
    ) -> bool:
        return (
            self.report is not None
            and self.report_error is None
        )


class TradingDayEndOfDayReportingCoordinator:
    """
    M12 wrapper around the exact existing M11 EOD coordinator.

    The upstream M11 coordinator remains authoritative and is
    always evaluated first.

    Reporting is a read-only postcondition of successful EOD
    closure and can never turn a successful close into a failure.
    """

    def __init__(
        self,
        *,
        end_of_day:
            TradingDayEndOfDayNotificationEvaluator,
        daily_report:
            DailyTradeReportBuilder,
    ) -> None:
        self._end_of_day = end_of_day
        self._daily_report = daily_report

    @property
    def end_of_day(
        self,
    ) -> TradingDayEndOfDayNotificationEvaluator:
        return self._end_of_day

    @property
    def daily_report(
        self,
    ) -> DailyTradeReportBuilder:
        return self._daily_report

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayEndOfDayReportingResult:
        if type(evaluated_at) is not datetime:
            raise TypeError(
                "evaluated_at must be datetime"
            )

        # ----------------------------------------------------
        # Authoritative M10/M11 evaluation happens first.
        #
        # Any exception here propagates unchanged.
        # M12 must not manufacture an EOD result.
        # ----------------------------------------------------

        notification_result = (
            self._end_of_day.evaluate(
                evaluated_at=evaluated_at
            )
        )

        end_of_day_result = (
            notification_result
            .end_of_day_result
        )

        if not end_of_day_result.complete:
            return TradingDayEndOfDayReportingResult(
                notification_result=(
                    notification_result
                ),
                report=None,
                report_error=None,
                evaluated_at=evaluated_at,
            )

        trading_date = (
            end_of_day_result
            .snapshot
            .trading_date
        )

        try:
            report = self._daily_report.build(
                trading_date=trading_date,
                generated_at=evaluated_at,
            )

            if report.trading_date != trading_date:
                raise RuntimeError(
                    "daily report trading_date does not "
                    "match authoritative M10 snapshot"
                )

        except Exception as exc:
            error = (
                f"{type(exc).__name__}: {exc}"
            )

            return TradingDayEndOfDayReportingResult(
                notification_result=(
                    notification_result
                ),
                report=None,
                report_error=error[:1000],
                evaluated_at=evaluated_at,
            )

        return TradingDayEndOfDayReportingResult(
            notification_result=(
                notification_result
            ),
            report=report,
            report_error=None,
            evaluated_at=evaluated_at,
        )


__all__ = [
    "DailyTradeReportBuilder",
    "TradingDayEndOfDayNotificationEvaluator",
    "TradingDayEndOfDayReportingCoordinator",
    "TradingDayEndOfDayReportingResult",
]
