"""
Phoenix M12 trading-date reporting.

A trading date may contain multiple runtime processes because of
restart/recovery. Daily reporting aggregates every durable
RuntimeSessionRecord for that trading date.

This module is strictly read-only.
"""

from __future__ import annotations

from datetime import (
    date,
    datetime,
)
from typing import Protocol

from sqlalchemy import select

from src.database.schema import (
    RuntimeSessionRecord,
)
from src.database.session import (
    DatabaseSessionManager,
)
from src.reporting.reporting_types import (
    DailyTradeAnalyticsSummary,
    DailyTradeReport,
    RuntimeTradeReport,
)


class DailyTradeReportIntegrityError(
    RuntimeError,
):
    """
    Durable runtime reports cannot safely be aggregated.
    """


class _TradingDateRuntimeReader(
    Protocol,
):
    def list_by_trading_date(
        self,
        trading_date: date,
    ) -> tuple[
        RuntimeSessionRecord,
        ...,
    ]:
        ...


class _RuntimeReportBuilder(
    Protocol,
):
    def build(
        self,
        *,
        runtime_id: str,
        generated_at: datetime,
    ) -> RuntimeTradeReport:
        ...


class TradingDateRuntimeQuery:
    """
    M12 read-only runtime-session query.

    Shares the exact existing DatabaseSessionManager.
    """

    def __init__(
        self,
        *,
        sessions: DatabaseSessionManager,
    ) -> None:
        if not isinstance(
            sessions,
            DatabaseSessionManager,
        ):
            raise TypeError(
                "sessions must be DatabaseSessionManager"
            )

        self._sessions = sessions

    @property
    def sessions(
        self,
    ) -> DatabaseSessionManager:
        return self._sessions

    def list_by_trading_date(
        self,
        trading_date: date,
    ) -> tuple[
        RuntimeSessionRecord,
        ...,
    ]:
        if type(trading_date) is not date:
            raise TypeError(
                "trading_date must be date"
            )

        with self._sessions.session_scope() as session:
            records = tuple(
                session.scalars(
                    select(
                        RuntimeSessionRecord
                    ).where(
                        RuntimeSessionRecord.trading_date
                        == trading_date
                    )
                ).all()
            )

        return tuple(
            sorted(
                records,
                key=lambda item: (
                    (
                        item.started_at
                        if item.started_at is not None
                        else item.updated_at
                    ),
                    item.updated_at,
                    item.runtime_id,
                ),
            )
        )


class DailyTradeReportService:
    """
    Build one immutable report covering all Phoenix runtimes
    belonging to one trading date.
    """

    def __init__(
        self,
        *,
        runtime_query: _TradingDateRuntimeReader,
        runtime_report: _RuntimeReportBuilder,
    ) -> None:
        self._runtime_query = runtime_query
        self._runtime_report = runtime_report

    @property
    def runtime_query(
        self,
    ) -> _TradingDateRuntimeReader:
        return self._runtime_query

    @property
    def runtime_report(
        self,
    ) -> _RuntimeReportBuilder:
        return self._runtime_report

    def build(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
    ) -> DailyTradeReport:
        if type(trading_date) is not date:
            raise TypeError(
                "trading_date must be date"
            )

        if type(generated_at) is not datetime:
            raise TypeError(
                "generated_at must be datetime"
            )

        runtimes = self._runtime_query.list_by_trading_date(
            trading_date
        )

        reports = tuple(
            self._runtime_report.build(
                runtime_id=runtime.runtime_id,
                generated_at=generated_at,
            )
            for runtime in runtimes
        )

        for report in reports:
            if report.trading_date != trading_date:
                raise DailyTradeReportIntegrityError(
                    "runtime report trading_date mismatch: "
                    f"{report.runtime_id}"
                )

        entries = tuple(
            entry
            for report in reports
            for entry in report.journal_entries
        )

        position_ids = [
            entry.position_id
            for entry in entries
        ]

        if (
            len(position_ids)
            != len(set(position_ids))
        ):
            raise DailyTradeReportIntegrityError(
                "duplicate durable position_id "
                "across runtime reports"
            )

        closed = tuple(
            entry
            for entry in entries
            if entry.open_quantity == 0
        )

        open_entries = tuple(
            entry
            for entry in entries
            if entry.open_quantity > 0
        )

        wins = tuple(
            entry
            for entry in closed
            if entry.realized_pnl > 0
        )

        losses = tuple(
            entry
            for entry in closed
            if entry.realized_pnl < 0
        )

        breakeven = tuple(
            entry
            for entry in closed
            if entry.realized_pnl == 0
        )

        realized_pnl = sum(
            entry.realized_pnl
            for entry in entries
        )

        gross_profit = sum(
            entry.realized_pnl
            for entry in entries
            if entry.realized_pnl > 0
        )

        gross_loss = abs(
            sum(
                entry.realized_pnl
                for entry in entries
                if entry.realized_pnl < 0
            )
        )

        average_closed_position_pnl = (
            sum(
                entry.realized_pnl
                for entry in closed
            )
            / len(closed)
            if closed
            else 0.0
        )

        average_win = (
            sum(
                entry.realized_pnl
                for entry in wins
            )
            / len(wins)
            if wins
            else 0.0
        )

        average_loss = (
            sum(
                entry.realized_pnl
                for entry in losses
            )
            / len(losses)
            if losses
            else 0.0
        )

        largest_win = (
            max(
                entry.realized_pnl
                for entry in wins
            )
            if wins
            else 0.0
        )

        largest_loss = (
            min(
                entry.realized_pnl
                for entry in losses
            )
            if losses
            else 0.0
        )

        win_rate_percent = (
            (
                len(wins)
                / len(closed)
            )
            * 100.0
            if closed
            else 0.0
        )

        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else None
        )

        analytics = DailyTradeAnalyticsSummary(
            trading_date=trading_date,
            runtime_count=len(reports),
            recovered_runtime_count=sum(
                1
                for report in reports
                if report.recovered
            ),
            failed_runtime_count=sum(
                1
                for report in reports
                if report.failure_code is not None
            ),
            position_count=len(entries),
            open_position_count=len(open_entries),
            closed_position_count=len(closed),
            winning_position_count=len(wins),
            losing_position_count=len(losses),
            breakeven_position_count=len(breakeven),
            realized_pnl=realized_pnl,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            average_closed_position_pnl=(
                average_closed_position_pnl
            ),
            average_win=average_win,
            average_loss=average_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            win_rate_percent=win_rate_percent,
            profit_factor=profit_factor,
            total_original_quantity=sum(
                entry.original_quantity
                for entry in entries
            ),
            total_closed_quantity=sum(
                entry.closed_quantity
                for entry in entries
            ),
            total_exit_filled_quantity=sum(
                entry.exit_filled_quantity
                for entry in entries
            ),
            exit_persistence_mismatch_count=sum(
                1
                for entry in entries
                if not entry.exit_persistence_in_sync
            ),
            audit_event_count=sum(
                len(report.timeline)
                for report in reports
            ),
            calculated_at=generated_at,
        )

        return DailyTradeReport(
            trading_date=trading_date,
            runtime_reports=reports,
            analytics=analytics,
            generated_at=generated_at,
        )


__all__ = [
    "DailyTradeReportIntegrityError",
    "DailyTradeReportService",
    "TradingDateRuntimeQuery",
]
