"""
Phoenix filled-position and exit-plan domain models.

These models represent:
    - an actually filled long option position
    - the mapped KS target
    - the calculated Phoenix target-booking plan
    - the future exit instruction

No broker-specific exit API logic belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from src.execution.execution_types import (
    BrokerOrderReference,
    OrderIntentId,
)
from src.execution.target_booking_policy import (
    TargetBookingPlan,
)
from src.option_selection.option_types import (
    OptionType,
    SelectedOption,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


class PositionState(str, Enum):
    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class ExitReason(str, Enum):
    TARGET = "TARGET"
    STOP_LOSS = "STOP_LOSS"
    FORCE_EXIT = "FORCE_EXIT"
    MANUAL = "MANUAL"


class ExitOrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


@dataclass(frozen=True, slots=True)
class FilledPositionId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError(
                "filled position id cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class FilledPosition:
    """
    Actual filled long-option position.

    entry_price must represent the broker-reported
    average fill price, not the original option LTP
    or submitted limit price.
    """

    position_id: FilledPositionId

    signal_id: SignalId
    entry_intent_id: OrderIntentId

    entry_broker_reference: BrokerOrderReference

    selected_option: SelectedOption

    level: EntryLevel

    quantity: int

    entry_price: float
    filled_at: datetime

    state: PositionState = PositionState.OPEN

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(
                "position quantity must be greater than zero"
            )

        if (
            self.quantity
            % self.selected_option.lot_size
            != 0
        ):
            raise ValueError(
                "position quantity must be a multiple "
                "of selected option lot size"
            )

        if not isfinite(
            self.entry_price
        ):
            raise ValueError(
                "entry_price must be finite"
            )

        if self.entry_price <= 0:
            raise ValueError(
                "entry_price must be greater than zero"
            )

        if (
            self.signal_id
            != self.selected_option
            .candidate.contract
            .underlying_symbol
        ):
            # Deliberately no validation here.
            # signal_id and underlying_symbol are different
            # domain concepts.
            pass

    @property
    def option_type(
        self,
    ) -> OptionType:
        return (
            self.selected_option.option_type
        )

    @property
    def security_id(
        self,
    ) -> str:
        return (
            self.selected_option.security_id
        )

    @property
    def symbol(
        self,
    ) -> str:
        return (
            self.selected_option.symbol
        )

    @property
    def lot_size(
        self,
    ) -> int:
        return (
            self.selected_option.lot_size
        )

    @property
    def lot_count(
        self,
    ) -> int:
        return (
            self.quantity
            // self.lot_size
        )


@dataclass(frozen=True, slots=True)
class ExitPlan:
    """
    Broker-independent planned exit for one filled position.

    mapped_target_price:
        Original mapped KS target price.

    target_plan:
        Result from TargetBookingPolicy.

    exit_price:
        Deterministic Phoenix exit trigger/limit price.

    The exit is not submitted merely by creating this model.
    """

    position_id: FilledPositionId

    security_id: str
    symbol: str

    option_type: OptionType

    quantity: int

    reason: ExitReason

    order_type: ExitOrderType

    mapped_target_price: float | None

    target_plan: TargetBookingPlan | None

    exit_price: float | None

    created_at: datetime

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError(
                "security_id cannot be empty"
            )

        if not self.symbol.strip():
            raise ValueError(
                "symbol cannot be empty"
            )

        if self.quantity <= 0:
            raise ValueError(
                "exit quantity must be greater than zero"
            )

        if (
            self.exit_price is not None
            and (
                not isfinite(
                    self.exit_price
                )
                or self.exit_price <= 0
            )
        ):
            raise ValueError(
                "exit_price must be a positive finite number"
            )

        if self.reason is ExitReason.TARGET:
            if self.target_plan is None:
                raise ValueError(
                    "target exit requires target_plan"
                )

            if self.mapped_target_price is None:
                raise ValueError(
                    "target exit requires mapped_target_price"
                )

            if self.exit_price is None:
                raise ValueError(
                    "target exit requires exit_price"
                )

            if (
                self.exit_price
                != self.target_plan
                .executable_target_price
            ):
                raise ValueError(
                    "exit_price must match target plan "
                    "executable target price"
                )

        if (
            self.reason is not ExitReason.TARGET
            and self.target_plan is not None
        ):
            raise ValueError(
                "non-target exit cannot contain target_plan"
            )