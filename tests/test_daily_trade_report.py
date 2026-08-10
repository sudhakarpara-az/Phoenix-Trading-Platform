from datetime import (
    date,
    datetime,
)

import pytest

from src.app.container import (
    build_persistence_foundation,
)
from src.database.engine import (
    DatabaseConfig,
)
from src.database.schema import (
    RuntimeSessionRecord,
)
from src.reporting.daily_report import (
    DailyTradeReportIntegrityError,
    DailyTradeReportService,
    TradingDateRuntimeQuery,
)
from src.reporting.reporting_types import (
    AuditTimelineEntry,
    RuntimeTradeReport,
    TradeAnalyticsSummary,
    TradeJournalEntry,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

OTHER_DATE = date(
    2026,
    8,
    11,
)

NOW = datetime(
    2026,
    8,
    10,
    9,
    15,
)

LATER = datetime(
    2026,
    8,
    10,
    10,
    0,
)

GENERATED = datetime(
    2026,
    8,
    10,
    15,
    20,
)


def runtime_record(
    *,
    runtime_id: str,
    trading_date: date = TRADING_DATE,
    started_at: datetime | None = NOW,
    updated_at: datetime = LATER,
) -> RuntimeSessionRecord:
    return RuntimeSessionRecord(
        runtime_id=runtime_id,
        trading_date=trading_date,
        mode="LIVE",
        state="STOPPED",
        started_at=started_at,
        updated_at=updated_at,
        stopped_at=updated_at,
        recovery_required=False,
        recovered=False,
        failure_code=None,
        failure_message=None,
        failure_component=None,
        failure_occurred_at=None,
        failure_recoverable=None,
    )


def journal_entry(
    *,
    runtime_id: str,
    position_id: str,
    realized_pnl: float,
) -> TradeJournalEntry:
    return TradeJournalEntry(
        runtime_id=runtime_id,
        position_id=position_id,
        signal_id=f"SIG-{position_id}",
        entry_order_intent_id=f"BUY-{position_id}",
        security_id=f"SEC-{position_id}",
        symbol="NIFTY-TEST",
        option_type="CALL",
        level="K5",
        original_quantity=65,
        open_quantity=0,
        closed_quantity=65,
        entry_price=100.0,
        entry_order_status="FILLED",
        entry_filled_quantity=65,
        entry_average_fill_price=100.0,
        exit_order_count=1,
        exit_fill_count=1,
        exit_filled_quantity=65,
        average_exit_price=110.0,
        realized_pnl=realized_pnl,
        latest_unrealized_pnl=0.0,
        latest_total_pnl=realized_pnl,
        latest_ltp=None,
        latest_pnl_at=None,
        state="CLOSED",
        opened_at=NOW,
        closed_at=LATER,
        exit_persistence_in_sync=True,
    )


def runtime_report(
    *,
    runtime_id: str,
    pnl: float,
    position_id: str,
) -> RuntimeTradeReport:
    entry = journal_entry(
        runtime_id=runtime_id,
        position_id=position_id,
        realized_pnl=pnl,
    )

    analytics = TradeAnalyticsSummary(
        runtime_id=runtime_id,
        position_count=1,
        open_position_count=0,
        closed_position_count=1,
        winning_position_count=(
            1 if pnl > 0 else 0
        ),
        losing_position_count=(
            1 if pnl < 0 else 0
        ),
        breakeven_position_count=(
            1 if pnl == 0 else 0
        ),
        realized_pnl=pnl,
        gross_profit=max(
            pnl,
            0.0,
        ),
        gross_loss=abs(
            min(
                pnl,
                0.0,
            )
        ),
        average_closed_position_pnl=pnl,
        average_win=(
            pnl if pnl > 0 else 0.0
        ),
        average_loss=(
            pnl if pnl < 0 else 0.0
        ),
        largest_win=(
            pnl if pnl > 0 else 0.0
        ),
        largest_loss=(
            pnl if pnl < 0 else 0.0
        ),
        win_rate_percent=(
            100.0 if pnl > 0 else 0.0
        ),
        profit_factor=None,
        total_original_quantity=65,
        total_closed_quantity=65,
        total_exit_filled_quantity=65,
        exit_persistence_mismatch_count=0,
        calculated_at=GENERATED,
    )

    timeline = (
        AuditTimelineEntry(
            event_id=f"EVENT-{runtime_id}",
            runtime_id=runtime_id,
            event_type="POSITION_CLOSED",
            entity_type="POSITION",
            entity_id=position_id,
            message=None,
            correlation_id=None,
            causation_id=None,
            payload_present=True,
            occurred_at=LATER,
        ),
    )

    return RuntimeTradeReport(
        runtime_id=runtime_id,
        trading_date=TRADING_DATE,
        mode="LIVE",
        runtime_state="STOPPED",
        started_at=NOW,
        updated_at=LATER,
        stopped_at=LATER,
        recovery_required=False,
        recovered=False,
        failure_code=None,
        failure_message=None,
        failure_component=None,
        failure_occurred_at=None,
        failure_recoverable=None,
        journal_entries=(entry,),
        analytics=analytics,
        timeline=timeline,
        generated_at=GENERATED,
    )


class FakeRuntimeQuery:
    def list_by_trading_date(
        self,
        trading_date: date,
    ) -> tuple[
        RuntimeSessionRecord,
        ...,
    ]:
        assert trading_date == TRADING_DATE

        return (
            runtime_record(
                runtime_id="RUNTIME-001"
            ),
            runtime_record(
                runtime_id="RUNTIME-002"
            ),
        )


class FakeRuntimeReport:
    def build(
        self,
        *,
        runtime_id: str,
        generated_at: datetime,
    ) -> RuntimeTradeReport:
        assert generated_at == GENERATED

        if runtime_id == "RUNTIME-001":
            return runtime_report(
                runtime_id=runtime_id,
                pnl=650.0,
                position_id="POS-001",
            )

        return runtime_report(
            runtime_id=runtime_id,
            pnl=-325.0,
            position_id="POS-002",
        )


def test_daily_report_aggregates_multiple_runtimes():
    report = DailyTradeReportService(
        runtime_query=FakeRuntimeQuery(),
        runtime_report=FakeRuntimeReport(),
    ).build(
        trading_date=TRADING_DATE,
        generated_at=GENERATED,
    )

    analytics = report.analytics

    assert analytics.runtime_count == 2
    assert analytics.position_count == 2
    assert analytics.closed_position_count == 2

    assert analytics.winning_position_count == 1
    assert analytics.losing_position_count == 1

    assert analytics.realized_pnl == 325.0
    assert analytics.gross_profit == 650.0
    assert analytics.gross_loss == 325.0

    assert analytics.profit_factor == 2.0
    assert analytics.win_rate_percent == 50.0

    assert analytics.audit_event_count == 2


def test_duplicate_position_across_runtimes_fails_closed():
    class DuplicateReports:
        def build(
            self,
            *,
            runtime_id: str,
            generated_at: datetime,
        ) -> RuntimeTradeReport:
            del generated_at

            return runtime_report(
                runtime_id=runtime_id,
                pnl=100.0,
                position_id="POS-SAME",
            )

    with pytest.raises(
        DailyTradeReportIntegrityError,
        match="duplicate durable position_id",
    ):
        DailyTradeReportService(
            runtime_query=FakeRuntimeQuery(),
            runtime_report=DuplicateReports(),
        ).build(
            trading_date=TRADING_DATE,
            generated_at=GENERATED,
        )


def test_trading_date_query_includes_zero_order_runtimes():
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    try:
        persistence.runtime_repository.add(
            runtime_record(
                runtime_id="RUNTIME-001"
            )
        )

        persistence.runtime_repository.add(
            runtime_record(
                runtime_id="RUNTIME-002",
                started_at=None,
                updated_at=GENERATED,
            )
        )

        persistence.runtime_repository.add(
            runtime_record(
                runtime_id="RUNTIME-OTHER",
                trading_date=OTHER_DATE,
            )
        )

        query = TradingDateRuntimeQuery(
            sessions=persistence.sessions
        )

        records = query.list_by_trading_date(
            TRADING_DATE
        )

        assert {
            record.runtime_id
            for record in records
        } == {
            "RUNTIME-001",
            "RUNTIME-002",
        }

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
