"""
Phoenix M12 runtime trade-report orchestration.

Combines:
    durable runtime session metadata
    trade journal
    trade analytics
    audit timeline

All dependencies are read-only projections of existing durable
Phoenix state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.database.schema import (
    RuntimeSessionRecord,
)
from src.reporting.audit_timeline import (
    AuditTimelineService,
)
from src.reporting.reporting_types import (
    RuntimeTradeReport,
)
from src.reporting.trade_analytics import (
    TradeAnalyticsService,
)
from src.reporting.trade_journal import (
    TradeJournalService,
)


class RuntimeTradeReportNotFoundError(
    LookupError,
):
    """
    Requested durable runtime session does not exist.
    """


class _RuntimeRepositoryReader(
    Protocol,
):
    def get(
        self,
        identity: str,
    ) -> RuntimeSessionRecord | None:
        ...


class RuntimeTradeReportService:
    """
    Build one complete immutable M12 runtime report.
    """

    def __init__(
        self,
        *,
        runtime_repository: _RuntimeRepositoryReader,
        trade_journal: TradeJournalService,
        trade_analytics: TradeAnalyticsService,
        audit_timeline: AuditTimelineService,
    ) -> None:
        self._runtime_repository = runtime_repository
        self._trade_journal = trade_journal
        self._trade_analytics = trade_analytics
        self._audit_timeline = audit_timeline

    @property
    def runtime_repository(
        self,
    ) -> _RuntimeRepositoryReader:
        return self._runtime_repository

    @property
    def trade_journal(
        self,
    ) -> TradeJournalService:
        return self._trade_journal

    @property
    def trade_analytics(
        self,
    ) -> TradeAnalyticsService:
        return self._trade_analytics

    @property
    def audit_timeline(
        self,
    ) -> AuditTimelineService:
        return self._audit_timeline

    def build(
        self,
        *,
        runtime_id: str,
        generated_at: datetime,
    ) -> RuntimeTradeReport:
        runtime_id = self._normalize_runtime_id(
            runtime_id
        )

        if type(generated_at) is not datetime:
            raise TypeError(
                "generated_at must be datetime"
            )

        runtime = self._runtime_repository.get(
            runtime_id
        )

        if runtime is None:
            raise RuntimeTradeReportNotFoundError(
                "runtime session not found: "
                f"{runtime_id}"
            )

        if runtime.runtime_id != runtime_id:
            raise RuntimeError(
                "runtime repository returned "
                "mismatched runtime identity"
            )

        entries = self._trade_journal.list_runtime(
            runtime_id
        )

        analytics = self._trade_analytics.summarize(
            runtime_id=runtime_id,
            entries=entries,
            calculated_at=generated_at,
        )

        timeline = self._audit_timeline.list_runtime(
            runtime_id
        )

        return RuntimeTradeReport(
            runtime_id=runtime.runtime_id,
            trading_date=runtime.trading_date,
            mode=runtime.mode,
            runtime_state=runtime.state,
            started_at=runtime.started_at,
            updated_at=runtime.updated_at,
            stopped_at=runtime.stopped_at,
            recovery_required=(
                runtime.recovery_required
            ),
            recovered=runtime.recovered,
            failure_code=runtime.failure_code,
            failure_message=(
                runtime.failure_message
            ),
            failure_component=(
                runtime.failure_component
            ),
            failure_occurred_at=(
                runtime.failure_occurred_at
            ),
            failure_recoverable=(
                runtime.failure_recoverable
            ),
            journal_entries=entries,
            analytics=analytics,
            timeline=timeline,
            generated_at=generated_at,
        )

    @staticmethod
    def _normalize_runtime_id(
        runtime_id: str,
    ) -> str:
        if not isinstance(
            runtime_id,
            str,
        ):
            raise TypeError(
                "runtime_id must be str"
            )

        normalized = runtime_id.strip()

        if not normalized:
            raise ValueError(
                "runtime_id cannot be empty"
            )

        return normalized


__all__ = [
    "RuntimeTradeReportNotFoundError",
    "RuntimeTradeReportService",
]
