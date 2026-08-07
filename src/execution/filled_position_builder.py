"""
Phoenix filled-position builder.

Converts a successfully FILLED broker order snapshot and
the original OrderIntent into a FilledPosition.

The broker-reported average fill price is authoritative.

No target calculation or broker exit logic belongs here.
"""

from __future__ import annotations

from datetime import datetime
from threading import RLock

from src.execution.broker_execution_provider import (
    BrokerOrderSnapshot,
)
from src.execution.execution_types import (
    BrokerOrderStatus,
    OrderIntent,
)
from src.execution.position_exit_types import (
    FilledPosition,
    FilledPositionId,
)


class FilledPositionBuilder:
    """
    Builds FilledPosition objects from completed entry orders.

    Requirements:
        - Broker order must be FILLED.
        - Filled quantity must equal requested quantity.
        - Broker average fill price must be present.
        - Broker reference must match the entry order context.
    """

    def __init__(self) -> None:
        self._sequence = 0
        self._lock = RLock()

    def build(
        self,
        *,
        intent: OrderIntent,
        broker_snapshot: BrokerOrderSnapshot,
        created_at: datetime | None = None,
    ) -> FilledPosition:
        """
        Convert a fully filled broker entry into FilledPosition.
        """

        if (
            broker_snapshot.status
            is not BrokerOrderStatus.FILLED
        ):
            raise ValueError(
                "filled position can only be built "
                "from FILLED broker order"
            )

        if (
            broker_snapshot.quantity
            != intent.quantity
        ):
            raise ValueError(
                "broker order quantity does not match "
                "order intent quantity"
            )

        if (
            broker_snapshot.filled_quantity
            != intent.quantity
        ):
            raise ValueError(
                "filled quantity does not match "
                "order intent quantity"
            )

        if broker_snapshot.average_price is None:
            raise ValueError(
                "FILLED broker order must contain "
                "average fill price"
            )

        if (
            broker_snapshot.broker_reference.broker_name
            .strip()
            .upper()
            == "DRY_RUN"
        ):
            raise ValueError(
                "dry-run order cannot create "
                "real filled position"
            )

        filled_at = (
            created_at
            or broker_snapshot.updated_at
        )

        return FilledPosition(
            position_id=self._next_position_id(
                filled_at
            ),
            signal_id=intent.signal.signal_id,
            entry_intent_id=intent.intent_id,
            entry_broker_reference=(
                broker_snapshot
                .broker_reference
            ),
            selected_option=(
                intent.selected_option
            ),
            level=intent.signal.level,
            quantity=intent.quantity,
            entry_price=(
                broker_snapshot.average_price
            ),
            filled_at=filled_at,
        )

    def _next_position_id(
        self,
        timestamp: datetime,
    ) -> FilledPositionId:
        """
        Generate process-local Phoenix position ID.
        """

        with self._lock:
            self._sequence += 1
            sequence = self._sequence

        return FilledPositionId(
            "POS-"
            f"{timestamp.strftime('%Y%m%d')}-"
            f"{sequence:06d}"
        )