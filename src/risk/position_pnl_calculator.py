"""
Phoenix M07 position P&L calculator.

Calculates realized, unrealized, and total P&L for long
option positions.

The authoritative cost basis is the actual M06 broker fill:

    FilledPosition.entry_price

No broker API logic or exit decision logic belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from src.execution.position_exit_types import (
    FilledPosition,
)
from src.risk.risk_types import (
    PositionPnL,
)


@dataclass(frozen=True, slots=True)
class ExitFill:
    """
    One executed SELL fill against a long option position.
    """

    quantity: int
    price: float
    filled_at: datetime

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(
                "exit fill quantity must be greater than zero"
            )

        if not isfinite(
            self.price
        ):
            raise ValueError(
                "exit fill price must be finite"
            )

        if self.price <= 0:
            raise ValueError(
                "exit fill price must be greater than zero"
            )


@dataclass(frozen=True, slots=True)
class PositionPnLCalculation:
    """
    Extended P&L calculation result.

    pnl:
        M07 PositionPnL snapshot.

    open_quantity:
        Quantity still exposed to market movement.

    closed_quantity:
        Quantity already sold.

    average_exit_price:
        Weighted average price across executed exits.
    """

    pnl: PositionPnL

    open_quantity: int
    closed_quantity: int

    average_exit_price: float | None


class PositionPnLCalculator:
    """
    Calculates P&L for one M06 FilledPosition.
    """

    def calculate(
        self,
        *,
        position: FilledPosition,
        current_ltp: float,
        exit_fills: tuple[ExitFill, ...] = (),
        calculated_at: datetime,
    ) -> PositionPnLCalculation:
        """
        Calculate current position P&L.

        Long-option semantics:

            realized:
                (exit - entry) * exited qty

            unrealized:
                (current LTP - entry) * open qty
        """

        self._validate_current_ltp(
            current_ltp
        )

        closed_quantity = sum(
            fill.quantity
            for fill in exit_fills
        )

        if (
            closed_quantity
            > position.quantity
        ):
            raise ValueError(
                "total exit fill quantity cannot exceed "
                "position quantity"
            )

        open_quantity = (
            position.quantity
            - closed_quantity
        )

        entry_price = (
            position.entry_price
        )

        realized_pnl = sum(
            (
                fill.price
                - entry_price
            )
            * fill.quantity
            for fill in exit_fills
        )

        unrealized_points = (
            current_ltp
            - entry_price
        )

        unrealized_pnl = (
            unrealized_points
            * open_quantity
        )

        total_pnl = (
            realized_pnl
            + unrealized_pnl
        )

        average_exit_price = (
            self._weighted_average_exit_price(
                exit_fills
            )
        )

        pnl = PositionPnL(
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=total_pnl,
            unrealized_points=unrealized_points,
            calculated_at=calculated_at,
        )

        return PositionPnLCalculation(
            pnl=pnl,
            open_quantity=open_quantity,
            closed_quantity=closed_quantity,
            average_exit_price=average_exit_price,
        )

    @staticmethod
    def _validate_current_ltp(
        current_ltp: float,
    ) -> None:
        if not isfinite(
            current_ltp
        ):
            raise ValueError(
                "current_ltp must be finite"
            )

        if current_ltp <= 0:
            raise ValueError(
                "current_ltp must be greater than zero"
            )

    @staticmethod
    def _weighted_average_exit_price(
        exit_fills: tuple[ExitFill, ...],
    ) -> float | None:
        if not exit_fills:
            return None

        total_quantity = sum(
            fill.quantity
            for fill in exit_fills
        )

        if total_quantity <= 0:
            return None

        total_value = sum(
            fill.price
            * fill.quantity
            for fill in exit_fills
        )

        return (
            total_value
            / total_quantity
        )