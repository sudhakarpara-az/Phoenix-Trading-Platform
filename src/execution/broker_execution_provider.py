"""
Broker-independent execution provider interface.

Defines the contract used by Phoenix execution services
to submit, cancel, and inspect broker orders.

No Dhan-specific API structures belong here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionResult,
    OrderIntent,
)


@dataclass(frozen=True, slots=True)
class BrokerOrderSnapshot:
    """
    Normalized broker order state.
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
            and self.average_price <= 0
        ):
            raise ValueError(
                "average_price must be greater than zero"
            )

        if (
            self.message is not None
            and not self.message.strip()
        ):
            raise ValueError(
                "message cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class BrokerCancellationResult:
    """
    Result of a broker cancellation request.
    """

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


class BrokerExecutionProvider(ABC):
    """
    Abstract broker execution interface.

    Phoenix execution logic depends only on this contract.
    """

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """
        Return stable broker identifier.
        """

        raise NotImplementedError

    @abstractmethod
    def submit_order(
        self,
        intent: OrderIntent,
    ) -> ExecutionResult:
        """
        Submit one validated order intent.
        """

        raise NotImplementedError

    @abstractmethod
    def cancel_order(
        self,
        broker_reference: BrokerOrderReference,
    ) -> BrokerCancellationResult:
        """
        Request cancellation of one broker order.
        """

        raise NotImplementedError

    @abstractmethod
    def get_order_status(
        self,
        broker_reference: BrokerOrderReference,
    ) -> BrokerOrderSnapshot:
        """
        Fetch normalized current state for one broker order.
        """

        raise NotImplementedError