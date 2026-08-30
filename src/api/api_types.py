"""
Phoenix M13 operator API read models.

These immutable values are transport-neutral.

They deliberately contain no broker clients, repositories,
runtime commands, or execution services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    date,
    datetime,
)


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorRuntimeView:
    """
    Read-only projection of the authoritative M08 runtime snapshot.
    """

    runtime_id: str
    trading_date: date

    mode: str
    state: str

    started_at: datetime | None
    updated_at: datetime
    stopped_at: datetime | None

    recovery_required: bool
    recovered: bool

    has_failure: bool


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorPositionSummary:
    """
    Read-only summary of the exact M07 PositionRegistry snapshot.

    tracked_position_count:
        all managed Phoenix positions currently retained by the
        registry.

    open_position_count:
        managed positions whose open_quantity is greater than zero.

    realized_pnl:
        persisted/in-memory realized P&L already owned by M07.
        M13 performs aggregation only; it does not recalculate
        execution P&L.
    """

    tracked_position_count: int
    open_position_count: int

    open_quantity: int
    realized_pnl: float

    def __post_init__(
        self,
    ) -> None:
        if self.tracked_position_count < 0:
            raise ValueError(
                "tracked_position_count cannot be negative"
            )

        if self.open_position_count < 0:
            raise ValueError(
                "open_position_count cannot be negative"
            )

        if (
            self.open_position_count
            > self.tracked_position_count
        ):
            raise ValueError(
                "open_position_count cannot exceed "
                "tracked_position_count"
            )

        if self.open_quantity < 0:
            raise ValueError(
                "open_quantity cannot be negative"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorSnapshot:
    """
    One internally coherent M13 operator read snapshot.
    """

    runtime: OperatorRuntimeView
    positions: OperatorPositionSummary

    captured_at: datetime


__all__ = [
    "OperatorPositionSummary",
    "OperatorRuntimeView",
    "OperatorSnapshot",
]
