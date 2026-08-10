from datetime import (
    date,
    datetime,
)

import pytest

from src.database.schema import (
    AuditEventRecord,
    OrderFillRecord,
    OrderRecord,
    PnLSnapshotRecord,
    PositionRecord,
    RuntimeSessionRecord,
)
from src.reporting.audit_timeline import (
    AuditTimelineService,
)
from src.reporting.runtime_report import (
    RuntimeTradeReportNotFoundError,
    RuntimeTradeReportService,
)
from src.reporting.trade_analytics import (
    TradeAnalyticsService,
)
from src.reporting.trade_journal import (
    TradeJournalService,
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
    9,
    15,
)

GENERATED = datetime(
    2026,
    8,
    10,
    15,
    20,
)


class EmptyOrderRepository:
    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        del runtime_id
        return ()


class EmptyFillRepository:
    def list_by_order(
        self,
        order_intent_id: str,
    ) -> tuple[
        OrderFillRecord,
        ...,
    ]:
        del order_intent_id
        return ()


class EmptyPositionRepository:
    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        PositionRecord,
        ...,
    ]:
        del runtime_id
        return ()


class EmptyPnLRepository:
    def list_by_position(
        self,
        position_id: str,
    ) -> tuple[
        PnLSnapshotRecord,
        ...,
    ]:
        del position_id
        return ()


class EmptyAuditRepository:
    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        AuditEventRecord,
        ...,
    ]:
        del runtime_id
        return ()


class FakeRuntimeRepository:
    def __init__(
        self,
        record:
            RuntimeSessionRecord | None,
    ) -> None:
        self.record = record

    def get(
        self,
        identity: str,
    ) -> RuntimeSessionRecord | None:
        if (
            self.record is not None
            and self.record.runtime_id
            == identity
        ):
            return self.record

        return None


def runtime_record(
) -> RuntimeSessionRecord:
    return RuntimeSessionRecord(
        runtime_id="RUNTIME-001",
        trading_date=TRADING_DATE,
        mode="DRY_RUN",
        state="STOPPED",
        started_at=NOW,
        updated_at=GENERATED,
        stopped_at=GENERATED,
        recovery_required=False,
        recovered=False,
        failure_code=None,
        failure_message=None,
        failure_component=None,
        failure_occurred_at=None,
        failure_recoverable=None,
    )


def report_service(
    runtime:
        RuntimeSessionRecord | None,
) -> RuntimeTradeReportService:
    journal = TradeJournalService(
        order_repository=(
            EmptyOrderRepository()
        ),
        order_fill_repository=(
            EmptyFillRepository()
        ),
        position_repository=(
            EmptyPositionRepository()
        ),
        pnl_repository=(
            EmptyPnLRepository()
        ),
    )

    return RuntimeTradeReportService(
        runtime_repository=(
            FakeRuntimeRepository(
                runtime
            )
        ),
        trade_journal=journal,
        trade_analytics=(
            TradeAnalyticsService()
        ),
        audit_timeline=(
            AuditTimelineService(
                audit_repository=(
                    EmptyAuditRepository()
                )
            )
        ),
    )


def test_runtime_report_combines_metadata_and_empty_analytics():
    report = report_service(
        runtime_record()
    ).build(
        runtime_id="RUNTIME-001",
        generated_at=GENERATED,
    )

    assert report.runtime_id == "RUNTIME-001"
    assert report.trading_date == TRADING_DATE
    assert report.mode == "DRY_RUN"
    assert report.runtime_state == "STOPPED"

    assert report.journal_entries == ()
    assert report.timeline == ()

    assert report.analytics.position_count == 0
    assert report.analytics.realized_pnl == 0

    assert report.generated_at == GENERATED


def test_missing_runtime_report_fails_explicitly():
    with pytest.raises(
        RuntimeTradeReportNotFoundError,
        match="runtime session not found",
    ):
        report_service(
            None
        ).build(
            runtime_id="RUNTIME-404",
            generated_at=GENERATED,
        )

def test_runtime_report_preserves_nullable_started_at():
    runtime = runtime_record()

    runtime.started_at = None

    report = report_service(
        runtime
    ).build(
        runtime_id="RUNTIME-001",
        generated_at=GENERATED,
    )

    assert report.started_at is None
