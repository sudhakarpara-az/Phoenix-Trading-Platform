import json
from datetime import (
    date,
    datetime,
)

from src.reporting.report_serializer import (
    ReportJsonSerializer,
)
from src.reporting.reporting_types import (
    DailyTradeAnalyticsSummary,
    DailyTradeReport,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

NOW = datetime(
    2026,
    8,
    10,
    15,
    20,
)


def daily_report() -> DailyTradeReport:
    analytics = DailyTradeAnalyticsSummary(
        trading_date=TRADING_DATE,
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
        calculated_at=NOW,
    )

    return DailyTradeReport(
        trading_date=TRADING_DATE,
        runtime_reports=(),
        analytics=analytics,
        generated_at=NOW,
    )


def test_daily_report_serializes_dates_as_iso_strings():
    payload = ReportJsonSerializer().to_dict(
        daily_report()
    )

    assert (
        payload["trading_date"]
        == "2026-08-10"
    )

    assert (
        payload["generated_at"]
        == "2026-08-10T15:20:00"
    )


def test_json_is_deterministic():
    serializer = ReportJsonSerializer()

    first = serializer.to_json(
        daily_report()
    )

    second = serializer.to_json(
        daily_report()
    )

    assert first == second

    decoded = json.loads(first)

    assert (
        decoded["analytics"]["runtime_count"]
        == 0
    )
