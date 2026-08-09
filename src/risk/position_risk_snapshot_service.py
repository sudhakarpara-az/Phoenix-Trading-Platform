"""
Phoenix M07 position risk snapshot service.

Builds a point-in-time risk view for one ManagedPosition.

Combines:
    - actual M06 entry fill
    - current option LTP
    - open / closed quantity
    - realized / unrealized / total P&L
    - configured stop loss
    - configured target
    - monetary downside risk
    - distance to stop and target

This service does not decide exits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from src.risk.position_pnl_calculator import (
    ExitFill,
    PositionPnLCalculator,
)
from src.risk.risk_types import (
    ManagedPosition,
    PositionRiskSnapshot,
    RiskTriggerType,
)


@dataclass(frozen=True, slots=True)
class PositionRiskMetrics:
    """
    Extended risk metrics around PositionRiskSnapshot.

    stop_distance_points:
        Current LTP minus stop price for long options.

        Positive:
            current premium remains above stop.

        Zero / negative:
            stop has been reached or crossed.

    target_distance_points:
        Executable target minus current LTP.

        Positive:
            target still above current LTP.

        Zero / negative:
            target has been reached or crossed.

    open_risk_points:
        Maximum remaining loss per option unit from the
        current LTP down to configured stop.

    open_risk_amount:
        open_risk_points * open quantity.

    entry_risk_amount:
        Configured entry-to-stop risk across current
        open quantity.
    """

    snapshot: PositionRiskSnapshot

    stop_distance_points: float | None

    target_distance_points: float | None

    open_risk_points: float | None

    open_risk_amount: float | None

    entry_risk_amount: float | None


class PositionRiskSnapshotService:
    """
    Builds point-in-time M07 risk snapshots.
    """

    def __init__(
        self,
        pnl_calculator: PositionPnLCalculator | None = None,
    ) -> None:
        self._pnl_calculator = (
            pnl_calculator
            or PositionPnLCalculator()
        )

    def build(
        self,
        *,
        managed_position: ManagedPosition,
        current_ltp: float,
        exit_fills: tuple[ExitFill, ...] = (),
        captured_at: datetime,
    ) -> PositionRiskMetrics:
        """
        Build a complete risk snapshot.

        The supplied exit fills must represent the executed
        SELL fills for the same managed position.
        """

        self._validate_ltp(
            current_ltp
        )

        pnl_result = (
            self._pnl_calculator.calculate(
                position=managed_position.position,
                current_ltp=current_ltp,
                exit_fills=exit_fills,
                calculated_at=captured_at,
            )
        )

        if (
            pnl_result.open_quantity
            != managed_position.open_quantity
        ):
            raise ValueError(
                "PnL open quantity does not match "
                "managed position open quantity"
            )

        if (
            pnl_result.closed_quantity
            != managed_position.closed_quantity
        ):
            raise ValueError(
                "PnL closed quantity does not match "
                "managed position closed quantity"
            )

        stop_distance_points = (
            self._stop_distance(
                managed_position=managed_position,
                current_ltp=current_ltp,
            )
        )

        target_distance_points = (
            self._target_distance(
                managed_position=managed_position,
                current_ltp=current_ltp,
            )
        )

        (
            open_risk_points,
            open_risk_amount,
            entry_risk_amount,
        ) = self._risk_amounts(
            managed_position=managed_position,
            current_ltp=current_ltp,
        )

        snapshot = PositionRiskSnapshot(
            current_ltp=current_ltp,
            open_quantity=(
                managed_position.open_quantity
            ),
            original_quantity=(
                managed_position.original_quantity
            ),
            closed_quantity=(
                managed_position.closed_quantity
            ),
            stop_loss=managed_position.stop_loss,
            target=managed_position.target,
            pnl=pnl_result.pnl,
            trigger=RiskTriggerType.NONE,
            captured_at=captured_at,
        )

        return PositionRiskMetrics(
            snapshot=snapshot,
            stop_distance_points=(
                stop_distance_points
            ),
            target_distance_points=(
                target_distance_points
            ),
            open_risk_points=(
                open_risk_points
            ),
            open_risk_amount=(
                open_risk_amount
            ),
            entry_risk_amount=(
                entry_risk_amount
            ),
        )

    @staticmethod
    def _stop_distance(
        *,
        managed_position: ManagedPosition,
        current_ltp: float,
    ) -> float | None:
        stop = managed_position.stop_loss

        if stop is None:
            return None

        return (
            current_ltp
            - stop.stop_price
        )

    @staticmethod
    def _target_distance(
        *,
        managed_position: ManagedPosition,
        current_ltp: float,
    ) -> float | None:
        target = managed_position.target

        if target is None:
            return None

        return (
            target.executable_price
            - current_ltp
        )

    @staticmethod
    def _risk_amounts(
        *,
        managed_position: ManagedPosition,
        current_ltp: float,
    ) -> tuple[
        float | None,
        float | None,
        float | None,
    ]:
        stop = managed_position.stop_loss

        if stop is None:
            return (
                None,
                None,
                None,
            )

        open_quantity = (
            managed_position.open_quantity
        )

        open_risk_points = max(
            current_ltp
            - stop.stop_price,
            0.0,
        )

        open_risk_amount = (
            open_risk_points
            * open_quantity
        )

        entry_risk_amount = (
            stop.risk_points
            * open_quantity
        )

        return (
            open_risk_points,
            open_risk_amount,
            entry_risk_amount,
        )

    @staticmethod
    def _validate_ltp(
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