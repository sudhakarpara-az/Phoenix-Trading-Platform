"""
Phoenix M13 operator reporting read service.

This service exposes the already-established M12 reporting
capabilities through a transport-neutral M13 boundary.

Ownership invariants:

- current runtime identity remains owned by M08;
- durable reports remain owned by M12;
- JSON serialization remains owned by M12;
- M13 creates no repository, session, report engine, broker
  client, or runtime state.
"""

from __future__ import annotations

from datetime import (
    date,
    datetime,
)
from typing import Protocol

from src.api.operator_snapshot import (
    RuntimeSnapshotReader,
)
from src.reporting.reporting_types import (
    DailyTradeReport,
    RuntimeTradeReport,
)


class RuntimeTradeReportReader(
    Protocol,
):
    """
    Narrow read-only view of M12 RuntimeTradeReportService.
    """

    def build(
        self,
        *,
        runtime_id: str,
        generated_at: datetime,
    ) -> RuntimeTradeReport:
        ...


class DailyTradeReportReader(
    Protocol,
):
    """
    Narrow read-only view of M12 DailyTradeReportService.
    """

    def build(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
    ) -> DailyTradeReport:
        ...


class OperatorReportSerializer(
    Protocol,
):
    """
    Narrow deterministic M12 serialization boundary.
    """

    def to_json(
        self,
        report: RuntimeTradeReport | DailyTradeReport,
        *,
        indent: int | None = None,
    ) -> str:
        ...


class OperatorReportingService:
    """
    Passive M13 facade over exact existing M08/M12 readers.
    """

    def __init__(
        self,
        *,
        runtime: RuntimeSnapshotReader,
        runtime_report: RuntimeTradeReportReader,
        daily_report: DailyTradeReportReader,
        serializer: OperatorReportSerializer,
    ) -> None:
        self._runtime = runtime
        self._runtime_report = runtime_report
        self._daily_report = daily_report
        self._serializer = serializer

    @property
    def runtime(
        self,
    ) -> RuntimeSnapshotReader:
        return self._runtime

    @property
    def runtime_report(
        self,
    ) -> RuntimeTradeReportReader:
        return self._runtime_report

    @property
    def daily_report(
        self,
    ) -> DailyTradeReportReader:
        return self._daily_report

    @property
    def serializer(
        self,
    ) -> OperatorReportSerializer:
        return self._serializer

    def current_runtime_report(
        self,
        *,
        generated_at: datetime,
    ) -> RuntimeTradeReport:
        self._validate_datetime(
            generated_at,
            name="generated_at",
        )

        # Read the authoritative M08 runtime exactly once.
        runtime = self._runtime.snapshot

        return self._runtime_report.build(
            runtime_id=runtime.runtime_id.value,
            generated_at=generated_at,
        )

    def daily_trade_report(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
    ) -> DailyTradeReport:
        self._validate_date(
            trading_date
        )

        self._validate_datetime(
            generated_at,
            name="generated_at",
        )

        return self._daily_report.build(
            trading_date=trading_date,
            generated_at=generated_at,
        )

    def current_runtime_json(
        self,
        *,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        report = self.current_runtime_report(
            generated_at=generated_at
        )

        return self._serializer.to_json(
            report,
            indent=indent,
        )

    def daily_trade_json(
        self,
        *,
        trading_date: date,
        generated_at: datetime,
        indent: int | None = None,
    ) -> str:
        report = self.daily_trade_report(
            trading_date=trading_date,
            generated_at=generated_at,
        )

        return self._serializer.to_json(
            report,
            indent=indent,
        )

    @staticmethod
    def _validate_date(
        trading_date: date,
    ) -> None:
        if type(trading_date) is not date:
            raise TypeError(
                "trading_date must be date"
            )

    @staticmethod
    def _validate_datetime(
        value: datetime,
        *,
        name: str,
    ) -> None:
        if type(value) is not datetime:
            raise TypeError(
                f"{name} must be datetime"
            )


__all__ = [
    "DailyTradeReportReader",
    "OperatorReportSerializer",
    "OperatorReportingService",
    "RuntimeTradeReportReader",
]
