"""
Phoenix exit execution interface.

Defines broker-independent SELL order models and the provider
contract used to submit, cancel, and inspect exit orders.

No Dhan-specific payload structure belongs here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitPlan,
    ExitReason,
    FilledPositionId,
)
from src.option_selection.option_types import (
    OptionType,
)


class ExitTransactionType(str, Enum):
    SELL = "SELL"


class ExitIntentState(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ExitOrderIntentId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError(
                "exit order intent id cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class ExitOrderIntent:
    """
    Broker-independent SELL instruction.

    Built from ExitPlan only after an actual FilledPosition exists.
    """

    intent_id: ExitOrderIntentId

    position_id: FilledPositionId

    security_id: str
    symbol: str

    option_type: OptionType

    transaction_type: ExitTransactionType

    order_type: ExitOrderType

    quantity: int

    price: float | None

    reason: ExitReason

    created_at: datetime

    state: ExitIntentState = ExitIntentState.CREATED

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError(
                "security_id cannot be empty"
            )

        if not self.symbol.strip():
            raise ValueError(
                "symbol cannot be empty"
            )

        if (
            self.transaction_type
            is not ExitTransactionType.SELL
        ):
            raise ValueError(
                "exit execution must use SELL transaction"
            )

        if self.quantity <= 0:
            raise ValueError(
                "exit quantity must be greater than zero"
            )

        if self.order_type is ExitOrderType.LIMIT:
            if self.price is None:
                raise ValueError(
                    "LIMIT exit requires price"
                )

            if (
                not isfinite(self.price)
                or self.price <= 0
            ):
                raise ValueError(
                    "LIMIT exit price must be a positive finite number"
                )

        if self.order_type is ExitOrderType.MARKET:
            if self.price is not None:
                raise ValueError(
                    "MARKET exit cannot specify price"
                )


@dataclass(frozen=True, slots=True)
class ExitExecutionResult:
    """
    Result of one exit submission attempt.
    """

    intent_id: ExitOrderIntentId

    success: bool

    status: BrokerOrderStatus

    broker_reference: BrokerOrderReference | None

    submitted_at: datetime

    message: str | None = None

    def __post_init__(self) -> None:
        if (
            self.success
            and self.broker_reference is None
        ):
            raise ValueError(
                "successful exit execution must contain broker_reference"
            )

        if (
            not self.success
            and self.status is BrokerOrderStatus.FILLED
        ):
            raise ValueError(
                "failed exit execution cannot have FILLED status"
            )

        if (
            self.message is not None
            and not self.message.strip()
        ):
            raise ValueError(
                "message cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class ExitOrderSnapshot:
    """
    Normalized current broker state for one SELL order.
    """

    broker_reference: BrokerOrderReference

    status: BrokerOrderStatus

    quantity: int
    filled_quantity: int

    average_price: float | None

    updated_at: datetime

    message: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(
                "quantity must be greater than zero"
            )

        if self.filled_quantity < 0:
            raise ValueError(
                "filled_quantity cannot be negative"
            )

        if self.filled_quantity > self.quantity:
            raise ValueError(
                "filled_quantity cannot exceed quantity"
            )

        if (
            self.average_price is not None
            and (
                not isfinite(self.average_price)
                or self.average_price <= 0
            )
        ):
            raise ValueError(
                "average_price must be a positive finite number"
            )


@dataclass(frozen=True, slots=True)
class ExitCancellationResult:
    broker_reference: BrokerOrderReference

    success: bool

    status: BrokerOrderStatus

    cancelled_at: datetime

    message: str | None = None

    def __post_init__(self) -> None:
        if (
            self.message is not None
            and not self.message.strip()
        ):
            raise ValueError(
                "message cannot be empty"
            )


class ExitExecutionProvider(ABC):
    """
    Broker-independent exit execution contract.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def submit_exit(
        self,
        intent: ExitOrderIntent,
    ) -> ExitExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_exit(
        self,
        broker_reference: BrokerOrderReference,
    ) -> ExitCancellationResult:
        raise NotImplementedError

    @abstractmethod
    def get_exit_status(
        self,
        broker_reference: BrokerOrderReference,
    ) -> ExitOrderSnapshot:
        raise NotImplementedError


class ExitOrderIntentBuilder:
    """
    Converts an ExitPlan into a broker-independent SELL intent.
    """

    def build(
        self,
        *,
        intent_id: ExitOrderIntentId,
        exit_plan: ExitPlan,
        created_at: datetime,
    ) -> ExitOrderIntent:
        return ExitOrderIntent(
            intent_id=intent_id,
            position_id=exit_plan.position_id,
            security_id=exit_plan.security_id,
            symbol=exit_plan.symbol,
            option_type=exit_plan.option_type,
            transaction_type=ExitTransactionType.SELL,
            order_type=exit_plan.order_type,
            quantity=exit_plan.quantity,
            price=exit_plan.exit_price,
            reason=exit_plan.reason,
            created_at=created_at,
        )