"""
Phoenix M12 immutable reporting read models.

These types are projections of existing durable Phoenix state.

They do not own:
    - broker execution,
    - order lifecycle,
    - position lifecycle,
    - P&L calculation,
    - persistence mutations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    date,
    datetime,
)
from math import isfinite


@dataclass(
    frozen=True,
    slots=True,
)
class TradeJournalEntry:
    """
    Reporting projection for one durable Phoenix position.

    actual exit execution is reconstructed from durable SELL
    OrderFillRecord rows.

    exit_persistence_in_sync intentionally exposes whether the
    durable exit-fill quantity currently matches the quantity
    already applied to PositionRecord.
    """

    runtime_id: str

    position_id: str
    signal_id: str
    entry_order_intent_id: str

    security_id: str
    symbol: str
    option_type: str
    level: str

    original_quantity: int
    open_quantity: int
    closed_quantity: int

    entry_price: float

    entry_order_status: str
    entry_filled_quantity: int
    entry_average_fill_price: float | None

    exit_order_count: int
    exit_fill_count: int
    exit_filled_quantity: int
    average_exit_price: float | None

    realized_pnl: float

    latest_unrealized_pnl: float
    latest_total_pnl: float
    latest_ltp: float | None
    latest_pnl_at: datetime | None

    state: str

    opened_at: datetime
    closed_at: datetime | None

    exit_persistence_in_sync: bool

    def __post_init__(
        self,
    ) -> None:
        for name in (
            "runtime_id",
            "position_id",
            "signal_id",
            "entry_order_intent_id",
            "security_id",
            "symbol",
            "option_type",
            "level",
            "entry_order_status",
            "state",
        ):
            value = getattr(
                self,
                name,
            )

            if (
                not isinstance(
                    value,
                    str,
                )
                or not value.strip()
            ):
                raise ValueError(
                    f"{name} cannot be empty"
                )

        for name in (
            "original_quantity",
            "open_quantity",
            "closed_quantity",
            "entry_filled_quantity",
            "exit_order_count",
            "exit_fill_count",
            "exit_filled_quantity",
        ):
            value = getattr(
                self,
                name,
            )

            if (
                type(value) is not int
                or value < 0
            ):
                raise ValueError(
                    f"{name} must be a non-negative integer"
                )

        if self.original_quantity <= 0:
            raise ValueError(
                "original_quantity must be positive"
            )

        if (
            self.open_quantity
            + self.closed_quantity
            != self.original_quantity
        ):
            raise ValueError(
                "open_quantity + closed_quantity "
                "must equal original_quantity"
            )

        for name in (
            "entry_price",
            "realized_pnl",
            "latest_unrealized_pnl",
            "latest_total_pnl",
        ):
            value = getattr(
                self,
                name,
            )

            if not isfinite(
                float(
                    value
                )
            ):
                raise ValueError(
                    f"{name} must be finite"
                )

        if self.entry_price <= 0:
            raise ValueError(
                "entry_price must be positive"
            )

        if (
            self.entry_average_fill_price
            is not None
            and (
                not isfinite(
                    self.entry_average_fill_price
                )
                or self.entry_average_fill_price <= 0
            )
        ):
            raise ValueError(
                "entry_average_fill_price must "
                "be positive and finite"
            )

        if (
            self.average_exit_price
            is not None
            and (
                not isfinite(
                    self.average_exit_price
                )
                or self.average_exit_price <= 0
            )
        ):
            raise ValueError(
                "average_exit_price must "
                "be positive and finite"
            )

        if (
            self.latest_ltp is not None
            and (
                not isfinite(
                    self.latest_ltp
                )
                or self.latest_ltp <= 0
            )
        ):
            raise ValueError(
                "latest_ltp must be positive and finite"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class TradeAnalyticsSummary:
    """
    Runtime-level M12 trade analytics.

    Closed-position win/loss statistics use quantity == 0 as
    the completion authority rather than trusting state text
    alone.

    realized_pnl includes any already-realized partial exits.
    """

    runtime_id: str

    position_count: int
    open_position_count: int
    closed_position_count: int

    winning_position_count: int
    losing_position_count: int
    breakeven_position_count: int

    realized_pnl: float
    gross_profit: float
    gross_loss: float

    average_closed_position_pnl: float
    average_win: float
    average_loss: float

    largest_win: float
    largest_loss: float

    win_rate_percent: float
    profit_factor: float | None

    total_original_quantity: int
    total_closed_quantity: int
    total_exit_filled_quantity: int

    exit_persistence_mismatch_count: int

    calculated_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class AuditTimelineEntry:
    """
    Safe reporting projection of one durable AuditEventRecord.

    Arbitrary AuditEventRecord.payload content is deliberately
    not exposed by this read model.

    Only correlation/causation linkage extracted from the
    persisted event envelope is surfaced.
    """

    event_id: str
    runtime_id: str
    event_type: str

    entity_type: str | None
    entity_id: str | None

    message: str | None

    correlation_id: str | None
    causation_id: str | None

    payload_present: bool

    occurred_at: datetime

    def __post_init__(
        self,
    ) -> None:
        for name in (
            "event_id",
            "runtime_id",
            "event_type",
        ):
            value = getattr(
                self,
                name,
            )

            if (
                not isinstance(
                    value,
                    str,
                )
                or not value.strip()
            ):
                raise ValueError(
                    f"{name} cannot be empty"
                )


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeTradeReport:
    """
    Complete immutable M12 report for one Phoenix runtime.

    This is a read model only. It does not become another
    persistence or execution state owner.
    """

    runtime_id: str
    trading_date: date

    mode: str
    runtime_state: str

    started_at: datetime | None
    updated_at: datetime
    stopped_at: datetime | None

    recovery_required: bool
    recovered: bool

    failure_code: str | None
    failure_message: str | None
    failure_component: str | None
    failure_occurred_at: datetime | None
    failure_recoverable: bool | None

    journal_entries: tuple[
        TradeJournalEntry,
        ...,
    ]

    analytics: TradeAnalyticsSummary

    timeline: tuple[
        AuditTimelineEntry,
        ...,
    ]

    generated_at: datetime

    def __post_init__(
        self,
    ) -> None:
        if (
            not isinstance(
                self.runtime_id,
                str,
            )
            or not self.runtime_id.strip()
        ):
            raise ValueError(
                "runtime_id cannot be empty"
            )

        if self.analytics.runtime_id != self.runtime_id:
            raise ValueError(
                "analytics runtime_id does not match report"
            )

        for entry in self.journal_entries:
            if entry.runtime_id != self.runtime_id:
                raise ValueError(
                    "journal runtime_id does not match report"
                )

        for event in self.timeline:
            if event.runtime_id != self.runtime_id:
                raise ValueError(
                    "timeline runtime_id does not match report"
                )


@dataclass(
    frozen=True,
    slots=True,
)
class DailyTradeAnalyticsSummary:
    """
    Trading-date analytics across all durable Phoenix runtimes
    belonging to the same trading date.
    """

    trading_date: date

    runtime_count: int
    recovered_runtime_count: int
    failed_runtime_count: int

    position_count: int
    open_position_count: int
    closed_position_count: int

    winning_position_count: int
    losing_position_count: int
    breakeven_position_count: int

    realized_pnl: float
    gross_profit: float
    gross_loss: float

    average_closed_position_pnl: float
    average_win: float
    average_loss: float

    largest_win: float
    largest_loss: float

    win_rate_percent: float
    profit_factor: float | None

    total_original_quantity: int
    total_closed_quantity: int
    total_exit_filled_quantity: int

    exit_persistence_mismatch_count: int
    audit_event_count: int

    calculated_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class DailyTradeReport:
    """
    Immutable M12 report covering one trading date.

    Individual RuntimeTradeReport objects remain independently
    traceable so restart/recovery runtime boundaries are retained.
    """

    trading_date: date

    runtime_reports: tuple[
        RuntimeTradeReport,
        ...,
    ]

    analytics: DailyTradeAnalyticsSummary

    generated_at: datetime

    def __post_init__(
        self,
    ) -> None:
        if (
            self.analytics.trading_date
            != self.trading_date
        ):
            raise ValueError(
                "daily analytics trading_date "
                "does not match report"
            )

        if (
            len(
                self.runtime_reports
            )
            != self.analytics.runtime_count
        ):
            raise ValueError(
                "runtime report count does not "
                "match daily analytics"
            )

        for report in self.runtime_reports:
            if (
                report.trading_date
                != self.trading_date
            ):
                raise ValueError(
                    "runtime report trading_date "
                    "does not match daily report"
                )


__all__ = [
    "AuditTimelineEntry",
    "DailyTradeAnalyticsSummary",
    "DailyTradeReport",
    "RuntimeTradeReport",
    "TradeAnalyticsSummary",
    "TradeJournalEntry",
]
