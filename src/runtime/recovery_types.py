"""
Phoenix M08 startup-recovery domain contracts.

Defines broker reconciliation snapshots and recovery results.

No SQLAlchemy or Dhan implementation belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Protocol


class BrokerRecoveryOrderState(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class BrokerRecoveryOrderSnapshot:
    broker_order_id: str

    state: BrokerRecoveryOrderState

    quantity: int

    filled_quantity: int

    average_fill_price: float | None

    checked_at: datetime

    def __post_init__(self) -> None:
        if not self.broker_order_id.strip():
            raise ValueError(
                "broker recovery order id cannot be empty"
            )

        if self.quantity <= 0:
            raise ValueError(
                "broker order quantity must be greater than zero"
            )

        if self.filled_quantity < 0:
            raise ValueError(
                "broker filled quantity cannot be negative"
            )

        if self.filled_quantity > self.quantity:
            raise ValueError(
                "broker filled quantity cannot exceed order quantity"
            )


@dataclass(frozen=True, slots=True)
class BrokerRecoveryPositionSnapshot:
    security_id: str

    net_quantity: int

    average_price: float | None

    checked_at: datetime

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError(
                "broker recovery security id cannot be empty"
            )


class RecoveryIssueCode(str, Enum):
    ORDER_MISSING_BROKER_ID = (
        "ORDER_MISSING_BROKER_ID"
    )

    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"

    ORDER_STATE_UNKNOWN = "ORDER_STATE_UNKNOWN"

    POSITION_QUANTITY_MISMATCH = (
        "POSITION_QUANTITY_MISMATCH"
    )

    BROKER_QUERY_FAILED = "BROKER_QUERY_FAILED"

    RESTORE_FAILED = "RESTORE_FAILED"


@dataclass(frozen=True, slots=True)
class RecoveryIssue:
    code: RecoveryIssueCode

    entity_type: str

    entity_id: str

    message: str

    def __post_init__(self) -> None:
        if not self.entity_type.strip():
            raise ValueError(
                "recovery issue entity type cannot be empty"
            )

        if not self.entity_id.strip():
            raise ValueError(
                "recovery issue entity id cannot be empty"
            )

        if not self.message.strip():
            raise ValueError(
                "recovery issue message cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class StartupRecoveryPlan:
    source_runtime_id: str | None

    persisted_runtime_state: str | None

    unresolved_order_count: int

    open_position_count: int

    recovery_required: bool


@dataclass(frozen=True, slots=True)
class StartupRecoveryResult:
    source_runtime_id: str | None

    recovered_orders: int

    recovered_positions: int

    issues: tuple[
        RecoveryIssue,
        ...
    ]

    completed: bool

    @property
    def issue_count(self) -> int:
        return len(
            self.issues
        )


class BrokerRecoveryProvider(Protocol):
    """
    Broker-truth boundary.

    Concrete Dhan implementation belongs outside runtime.
    """

    def get_order_snapshot(
        self,
        *,
        broker_order_id: str,
        checked_at: datetime,
    ) -> BrokerRecoveryOrderSnapshot:
        ...

    def get_position_snapshot(
        self,
        *,
        security_id: str,
        checked_at: datetime,
    ) -> BrokerRecoveryPositionSnapshot:
        ...


class RecoveryStateRestorer(Protocol):
    """
    Rehydrates confirmed broker/persisted truth into M04-M07.

    T08 uses this narrow boundary rather than reconstructing
    existing engines internally.
    """

    def restore_order(
        self,
        *,
        persisted_order: Any,
        broker_snapshot: BrokerRecoveryOrderSnapshot,
    ) -> None:
        ...

    def restore_position(
        self,
        *,
        persisted_position: Any,
        broker_snapshot: BrokerRecoveryPositionSnapshot,
    ) -> None:
        ...