from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import Protocol

from src.risk.position_pnl_tracker import (
    PositionPnLState,
)
from src.risk.risk_types import (
    ManagedPosition,
)


class OperatorPositionRegistryReader(
    Protocol,
):
    def open_positions(
        self,
    ) -> tuple[
        ManagedPosition,
        ...,
    ]:
        ...


class OperatorPositionPnLReader(
    Protocol,
):
    def get(
        self,
        position_id: Any,
    ) -> PositionPnLState | None:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorPositionView:
    position_id: str
    risk_id: str

    symbol: str
    security_id: str
    lot_size: int

    entry_price: float

    original_quantity: int
    open_quantity: int
    closed_quantity: int

    state: str

    realized_pnl: float

    pnl_available: bool

    unrealized_pnl: float | None
    total_pnl: float | None
    unrealized_points: float | None

    latest_ltp: float | None
    latest_mark_at: datetime | None

    created_at: datetime
    updated_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorPositionsView:
    positions: tuple[
        OperatorPositionView,
        ...,
    ]

    open_count: int
    open_quantity: int

    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float

    captured_at: datetime


class OperatorPositionService:
    """
    Passive M13 projection of exact retained M07 position
    and P&L owners.

    PositionRegistry remains authoritative for current open
    exposure.

    PositionPnLTracker remains authoritative for current LTP,
    latest mark, realized/unrealized P&L and total P&L.

    Missing P&L tracker state is represented explicitly through
    pnl_available=False. M13 does not synthesize an LTP or
    unrealized P&L.
    """

    def __init__(
        self,
        *,
        registry: OperatorPositionRegistryReader,
        pnl_tracker: OperatorPositionPnLReader,
    ) -> None:
        self._registry = registry
        self._pnl_tracker = pnl_tracker

    @property
    def registry(
        self,
    ) -> OperatorPositionRegistryReader:
        return self._registry

    @property
    def pnl_tracker(
        self,
    ) -> OperatorPositionPnLReader:
        return self._pnl_tracker

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorPositionsView:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be a datetime"
            )

        positions = (
            self._registry.open_positions()
        )

        projected: list[
            OperatorPositionView
        ] = []

        total_open_quantity = 0
        total_realized_pnl = 0.0
        total_unrealized_pnl = 0.0

        for position in positions:
            pnl = self._pnl_tracker.get(
                position.position_id
            )

            if pnl is None:
                realized_pnl = (
                    position.realized_pnl
                )

                unrealized_pnl = None
                total_pnl = None
                unrealized_points = None
                latest_ltp = None
                latest_mark_at = None

            else:
                realized_pnl = (
                    pnl.realized_pnl
                )

                unrealized_pnl = (
                    pnl.unrealized_pnl
                )

                total_pnl = (
                    pnl.total_pnl
                )

                unrealized_points = (
                    pnl.unrealized_points
                )

                latest_ltp = (
                    pnl.latest_ltp
                )

                latest_mark_at = (
                    pnl.latest_mark_at
                )

                total_unrealized_pnl += (
                    pnl.unrealized_pnl
                )

            total_open_quantity += (
                position.open_quantity
            )

            total_realized_pnl += (
                realized_pnl
            )

            projected.append(
                OperatorPositionView(
                    position_id=(
                        position
                        .position_id
                        .value
                    ),
                    risk_id=(
                        position
                        .risk_id
                        .value
                    ),
                    symbol=(
                        position.symbol
                    ),
                    security_id=(
                        position.security_id
                    ),
                    lot_size=(
                        position.lot_size
                    ),
                    entry_price=(
                        position.entry_price
                    ),
                    original_quantity=(
                        position
                        .original_quantity
                    ),
                    open_quantity=(
                        position
                        .open_quantity
                    ),
                    closed_quantity=(
                        position
                        .closed_quantity
                    ),
                    state=(
                        position
                        .state
                        .value
                    ),
                    realized_pnl=(
                        realized_pnl
                    ),
                    pnl_available=(
                        pnl is not None
                    ),
                    unrealized_pnl=(
                        unrealized_pnl
                    ),
                    total_pnl=(
                        total_pnl
                    ),
                    unrealized_points=(
                        unrealized_points
                    ),
                    latest_ltp=(
                        latest_ltp
                    ),
                    latest_mark_at=(
                        latest_mark_at
                    ),
                    created_at=(
                        position.created_at
                    ),
                    updated_at=(
                        position.updated_at
                    ),
                )
            )

        return OperatorPositionsView(
            positions=tuple(
                projected
            ),
            open_count=len(
                projected
            ),
            open_quantity=(
                total_open_quantity
            ),
            realized_pnl=(
                total_realized_pnl
            ),
            unrealized_pnl=(
                total_unrealized_pnl
            ),
            total_pnl=(
                total_realized_pnl
                + total_unrealized_pnl
            ),
            captured_at=captured_at,
        )


__all__ = [
    "OperatorPositionPnLReader",
    "OperatorPositionRegistryReader",
    "OperatorPositionService",
    "OperatorPositionView",
    "OperatorPositionsView",
]
