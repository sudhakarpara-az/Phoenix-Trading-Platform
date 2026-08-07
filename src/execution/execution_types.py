"""
Phoenix execution domain models.

These objects represent broker-independent order intent
and execution lifecycle data.

No Dhan-specific API calls belong in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from src.option_selection.option_types import (
    OptionType,
    SelectedOption,
)
from src.signals.signal_types import TradingSignal


class TransactionType(str, Enum):
    BUY = "BUY"


class OrderType(str, Enum):
    LIMIT = "LIMIT"


class ExecutionMode(str, Enum):
    DRY_RUN = "DRY_RUN"
    LIVE = "LIVE"


class OrderIntentState(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class BrokerOrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OrderIntentId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError(
                "order intent id cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """
    Broker-independent Phoenix order instruction.
    """

    intent_id: OrderIntentId

    signal: TradingSignal
    selected_option: SelectedOption

    transaction_type: TransactionType
    order_type: OrderType

    quantity: int
    limit_price: float

    execution_mode: ExecutionMode

    created_at: datetime

    state: OrderIntentState = OrderIntentState.CREATED

    def __post_init__(self) -> None:
        if self.transaction_type is not TransactionType.BUY:
            raise ValueError(
                "Phoenix currently supports BUY orders only"
            )

        if self.order_type is not OrderType.LIMIT:
            raise ValueError(
                "Phoenix currently supports LIMIT orders only"
            )

        if self.quantity <= 0:
            raise ValueError(
                "quantity must be greater than zero"
            )

        if not isfinite(self.limit_price):
            raise ValueError(
                "limit_price must be a finite number"
            )

        if self.limit_price <= 0:
            raise ValueError(
                "limit_price must be greater than zero"
            )

        if (
            self.signal.direction.value
            != self.selected_option.option_type.value
        ):
            raise ValueError(
                "signal direction and selected option type must match"
            )


@dataclass(frozen=True, slots=True)
class BrokerOrderReference:
    """
    Broker acknowledgement identifier.
    """

    broker_name: str
    order_id: str

    def __post_init__(self) -> None:
        if not self.broker_name.strip():
            raise ValueError(
                "broker_name cannot be empty"
            )

        if not self.order_id.strip():
            raise ValueError(
                "order_id cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """
    Result of one broker execution attempt.
    """

    intent_id: OrderIntentId

    success: bool
    status: BrokerOrderStatus

    broker_reference: BrokerOrderReference | None

    submitted_at: datetime
    message: str | None = None

    def __post_init__(self) -> None:
        if self.success and self.broker_reference is None:
            raise ValueError(
                "successful execution must contain broker_reference"
            )

        if (
            not self.success
            and self.status is BrokerOrderStatus.FILLED
        ):
            raise ValueError(
                "failed execution cannot have FILLED status"
            )

        if self.message is not None and not self.message.strip():
            raise ValueError(
                "message cannot be empty"
            )