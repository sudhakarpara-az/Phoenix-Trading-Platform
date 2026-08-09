"""
Phoenix M07 position and risk domain models.

M06 owns broker execution and produces FilledPosition.

M07 owns the runtime management state around that filled position:
    - open / remaining quantity
    - realized and unrealized P&L
    - stop-loss state
    - target state
    - exit trigger state
    - position-management lifecycle

No broker API logic belongs in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from src.execution.position_exit_types import (
    FilledPosition,
    FilledPositionId,
)


class ManagedPositionState(str, Enum):
    """
    M07 runtime position lifecycle.

    This is intentionally separate from the frozen M06
    FilledPosition model.
    """

    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    PARTIALLY_EXITED = "PARTIALLY_EXITED"
    CLOSED = "CLOSED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    FAILED = "FAILED"


class RiskTriggerType(str, Enum):
    """
    Reason M07 wants the position exited.
    """

    NONE = "NONE"

    TARGET = "TARGET"
    STOP_LOSS = "STOP_LOSS"
    FORCE_EXIT = "FORCE_EXIT"
    MANUAL = "MANUAL"


class StopLossState(str, Enum):
    """
    Runtime stop-loss state.
    """

    NOT_CONFIGURED = "NOT_CONFIGURED"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    DISABLED = "DISABLED"


class TargetState(str, Enum):
    """
    Runtime target state.
    """

    NOT_CONFIGURED = "NOT_CONFIGURED"
    ARMED = "ARMED"
    BOOKING_ZONE = "BOOKING_ZONE"
    TRIGGERED = "TRIGGERED"
    DISABLED = "DISABLED"


@dataclass(frozen=True, slots=True)
class PositionRiskId:
    """
    Stable identifier for one M07 managed-position state.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError(
                "position risk id cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class StopLossDefinition:
    """
    Stop-loss definition for one long-option position.

    stop_price:
        Option premium at which the stop becomes triggered.

    risk_points:
        Difference between actual entry price and stop price.
    """

    stop_price: float

    risk_points: float

    state: StopLossState = StopLossState.ARMED

    def __post_init__(self) -> None:
        self._validate_positive_finite(
            self.stop_price,
            "stop_price",
        )

        self._validate_positive_finite(
            self.risk_points,
            "risk_points",
        )

        if self.state is StopLossState.NOT_CONFIGURED:
            raise ValueError(
                "configured stop loss cannot have "
                "NOT_CONFIGURED state"
            )

    @staticmethod
    def _validate_positive_finite(
        value: float,
        name: str,
    ) -> None:
        if not isfinite(value):
            raise ValueError(
                f"{name} must be finite"
            )

        if value <= 0:
            raise ValueError(
                f"{name} must be greater than zero"
            )


@dataclass(frozen=True, slots=True)
class TargetDefinition:
    """
    Runtime target definition.

    executable_price:
        Deterministic option-premium trigger.

    mapped_target_price:
        Original option-premium target associated with the
        underlying strategy target.

    booking_zone_start / booking_zone_end:
        Profit-booking zone retained from M06 target policy.
    """

    executable_price: float

    mapped_target_price: float

    booking_zone_start: float

    booking_zone_end: float

    state: TargetState = TargetState.ARMED

    def __post_init__(self) -> None:
        values = {
            "executable_price": (
                self.executable_price
            ),
            "mapped_target_price": (
                self.mapped_target_price
            ),
            "booking_zone_start": (
                self.booking_zone_start
            ),
            "booking_zone_end": (
                self.booking_zone_end
            ),
        }

        for name, value in values.items():
            if not isfinite(value):
                raise ValueError(
                    f"{name} must be finite"
                )

            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )

        if (
            self.booking_zone_start
            > self.booking_zone_end
        ):
            raise ValueError(
                "booking_zone_start cannot exceed "
                "booking_zone_end"
            )

        if (
            self.executable_price
            < self.booking_zone_start
            or self.executable_price
            > self.booking_zone_end
        ):
            raise ValueError(
                "executable_price must be inside "
                "booking zone"
            )

        if (
            self.mapped_target_price
            < self.executable_price
        ):
            raise ValueError(
                "mapped_target_price cannot be below "
                "executable_price"
            )

        if self.state is TargetState.NOT_CONFIGURED:
            raise ValueError(
                "configured target cannot have "
                "NOT_CONFIGURED state"
            )


@dataclass(frozen=True, slots=True)
class PositionPnL:
    """
    P&L snapshot for one long-option position.

    realized_pnl:
        P&L already locked by executed SELL quantity.

    unrealized_pnl:
        Mark-to-market P&L on remaining open quantity.

    total_pnl:
        realized + unrealized.

    unrealized_points:
        Current option LTP minus actual average entry price.
    """

    realized_pnl: float

    unrealized_pnl: float

    total_pnl: float

    unrealized_points: float

    calculated_at: datetime

    def __post_init__(self) -> None:
        for name, value in {
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.total_pnl,
            "unrealized_points": (
                self.unrealized_points
            ),
        }.items():
            if not isfinite(value):
                raise ValueError(
                    f"{name} must be finite"
                )

        expected_total = (
            self.realized_pnl
            + self.unrealized_pnl
        )

        if abs(
            self.total_pnl
            - expected_total
        ) > 1e-9:
            raise ValueError(
                "total_pnl must equal realized_pnl "
                "+ unrealized_pnl"
            )


@dataclass(frozen=True, slots=True)
class PositionRiskSnapshot:
    """
    Point-in-time risk view for one managed position.
    """

    current_ltp: float

    open_quantity: int

    original_quantity: int

    closed_quantity: int

    stop_loss: StopLossDefinition | None

    target: TargetDefinition | None

    pnl: PositionPnL

    trigger: RiskTriggerType

    captured_at: datetime

    def __post_init__(self) -> None:
        if not isfinite(
            self.current_ltp
        ):
            raise ValueError(
                "current_ltp must be finite"
            )

        if self.current_ltp <= 0:
            raise ValueError(
                "current_ltp must be greater than zero"
            )

        if self.original_quantity <= 0:
            raise ValueError(
                "original_quantity must be greater than zero"
            )

        if self.open_quantity < 0:
            raise ValueError(
                "open_quantity cannot be negative"
            )

        if self.closed_quantity < 0:
            raise ValueError(
                "closed_quantity cannot be negative"
            )

        if (
            self.open_quantity
            + self.closed_quantity
            != self.original_quantity
        ):
            raise ValueError(
                "open_quantity + closed_quantity must equal "
                "original_quantity"
            )

        if (
            self.trigger is RiskTriggerType.STOP_LOSS
            and self.stop_loss is None
        ):
            raise ValueError(
                "STOP_LOSS trigger requires stop_loss"
            )

        if (
            self.trigger is RiskTriggerType.TARGET
            and self.target is None
        ):
            raise ValueError(
                "TARGET trigger requires target"
            )


@dataclass(frozen=True, slots=True)
class ManagedPosition:
    """
    M07 management record for one M06 FilledPosition.

    The original FilledPosition remains authoritative for:
        - actual entry price
        - contract identity
        - original quantity
        - entry signal
        - broker entry reference

    M07 adds operational risk-management state around it.
    """

    risk_id: PositionRiskId

    position: FilledPosition

    open_quantity: int

    closed_quantity: int

    realized_pnl: float

    state: ManagedPositionState

    stop_loss: StopLossDefinition | None

    target: TargetDefinition | None

    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.open_quantity < 0:
            raise ValueError(
                "open_quantity cannot be negative"
            )

        if self.closed_quantity < 0:
            raise ValueError(
                "closed_quantity cannot be negative"
            )

        if (
            self.open_quantity
            + self.closed_quantity
            != self.position.quantity
        ):
            raise ValueError(
                "managed quantities must equal "
                "filled position quantity"
            )

        if not isfinite(
            self.realized_pnl
        ):
            raise ValueError(
                "realized_pnl must be finite"
            )

        if self.updated_at < self.created_at:
            raise ValueError(
                "updated_at cannot be before created_at"
            )

        if (
            self.state
            is ManagedPositionState.CLOSED
            and self.open_quantity != 0
        ):
            raise ValueError(
                "CLOSED position must have zero open quantity"
            )

        if (
            self.state
            is ManagedPositionState.OPEN
            and self.open_quantity <= 0
        ):
            raise ValueError(
                "OPEN position must have positive "
                "open quantity"
            )

        if (
            self.state
            is ManagedPositionState.PARTIALLY_EXITED
            and (
                self.open_quantity <= 0
                or self.closed_quantity <= 0
            )
        ):
            raise ValueError(
                "PARTIALLY_EXITED position requires both "
                "open and closed quantity"
            )

    @property
    def position_id(
        self,
    ) -> FilledPositionId:
        return self.position.position_id

    @property
    def entry_price(
        self,
    ) -> float:
        """
        Actual M06 broker average fill price.
        """

        return self.position.entry_price

    @property
    def original_quantity(
        self,
    ) -> int:
        return self.position.quantity

    @property
    def symbol(
        self,
    ) -> str:
        return self.position.symbol

    @property
    def security_id(
        self,
    ) -> str:
        return self.position.security_id

    @property
    def lot_size(
        self,
    ) -> int:
        return self.position.lot_size

    @property
    def is_open(
        self,
    ) -> bool:
        return self.open_quantity > 0