"""
Phoenix exit-plan builder.

Converts a FilledPosition into a broker-independent ExitPlan.

Target exits:
    FilledPosition
        +
    mapped KS target price
        ↓
    TargetBookingPolicy
        ↓
    TargetBookingPlan
        ↓
    ExitPlan

Non-target exits:
    FORCE_EXIT / STOP_LOSS / MANUAL
        ↓
    ExitPlan without target metadata

No broker SELL request belongs in this module.
"""

from __future__ import annotations

from datetime import datetime

from src.execution.position_exit_types import (
    ExitOrderType,
    ExitPlan,
    ExitReason,
    FilledPosition,
)
from src.execution.target_booking_policy import (
    TargetBookingPolicy,
)


class ExitPlanBuilder:
    """
    Builds broker-independent Phoenix exit plans.
    """

    def __init__(
        self,
        target_booking_policy: TargetBookingPolicy,
    ) -> None:
        self._target_booking_policy = (
            target_booking_policy
        )

    def build_target_exit(
        self,
        *,
        position: FilledPosition,
        mapped_target_price: float,
        created_at: datetime,
    ) -> ExitPlan:
        """
        Build a target-based LIMIT exit.

        The actual FilledPosition.entry_price is used as
        the starting point for target calculation.
        """

        target_plan = (
            self._target_booking_policy.calculate(
                entry_price=position.entry_price,
                mapped_target_price=mapped_target_price,
            )
        )

        return ExitPlan(
            position_id=position.position_id,
            security_id=position.security_id,
            symbol=position.symbol,
            option_type=position.option_type,
            quantity=position.quantity,
            reason=ExitReason.TARGET,
            order_type=ExitOrderType.LIMIT,
            mapped_target_price=(
                mapped_target_price
            ),
            target_plan=target_plan,
            exit_price=(
                target_plan
                .executable_target_price
            ),
            created_at=created_at,
        )

    def build_force_exit(
        self,
        *,
        position: FilledPosition,
        created_at: datetime,
        quantity: int | None = None,
    ) -> ExitPlan:
        """
        Build force-exit instruction.

        quantity defaults to the full position quantity.

        During reconciliation, quantity may represent only the
        remaining open position after a partial target fill.
        """

        exit_quantity = (
            position.quantity
            if quantity is None
            else quantity
        )

        if exit_quantity <= 0:
            raise ValueError(
                "force exit quantity must be greater than zero"
            )

        if exit_quantity > position.quantity:
            raise ValueError(
                "force exit quantity cannot exceed position quantity"
            )

        return ExitPlan(
            position_id=position.position_id,
            security_id=position.security_id,
            symbol=position.symbol,
            option_type=position.option_type,
            quantity=exit_quantity,
            reason=ExitReason.FORCE_EXIT,
            order_type=ExitOrderType.MARKET,
            mapped_target_price=None,
            target_plan=None,
            exit_price=None,
            created_at=created_at,
        )

    def build_stop_loss_exit(
        self,
        *,
        position: FilledPosition,
        created_at: datetime,
        exit_price: float | None = None,
        order_type: ExitOrderType = (
            ExitOrderType.MARKET
        ),
    ) -> ExitPlan:
        """
        Build stop-loss exit instruction.

        Stop-loss price logic itself is not calculated here.
        This method receives an already determined exit price
        when a LIMIT stop-loss exit is required.
        """

        return self._build_non_target_exit(
            position=position,
            reason=ExitReason.STOP_LOSS,
            order_type=order_type,
            created_at=created_at,
            exit_price=exit_price,
        )

    def build_manual_exit(
        self,
        *,
        position: FilledPosition,
        created_at: datetime,
        quantity: int | None = None,
        order_type: ExitOrderType = (
            ExitOrderType.MARKET
        ),
        exit_price: float | None = None,
    ) -> ExitPlan:
        """
        Build manual exit instruction.
        """

        return self._build_non_target_exit(
            position=position,
            reason=ExitReason.MANUAL,
            order_type=order_type,
            created_at=created_at,
            exit_price=exit_price,
            quantity=quantity,
        )

    @staticmethod
    def _build_non_target_exit(
        *,
        position: FilledPosition,
        reason: ExitReason,
        order_type: ExitOrderType,
        created_at: datetime,
        exit_price: float | None = None,
        quantity: int | None = None,
    ) -> ExitPlan:
        exit_quantity = (
            position.quantity
            if quantity is None
            else quantity
        )

        if exit_quantity <= 0:
            raise ValueError(
                "exit quantity must be greater than zero"
            )

        if exit_quantity > position.quantity:
            raise ValueError(
                "exit quantity cannot exceed position quantity"
            )

        if reason is ExitReason.TARGET:
            raise ValueError(
                "target exits must use build_target_exit"
            )

        if (
            order_type is ExitOrderType.LIMIT
            and exit_price is None
        ):
            raise ValueError(
                "LIMIT exit requires exit_price"
            )

        if (
            order_type is ExitOrderType.MARKET
            and exit_price is not None
        ):
            raise ValueError(
                "MARKET exit cannot specify exit_price"
            )

        return ExitPlan(
            position_id=position.position_id,
            security_id=position.security_id,
            symbol=position.symbol,
            option_type=position.option_type,
            quantity=exit_quantity,
            reason=reason,
            order_type=order_type,
            mapped_target_price=None,
            target_plan=None,
            exit_price=exit_price,
            created_at=created_at,
        )
