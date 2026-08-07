"""
Phoenix dry-run execution simulator.

Simulates an accepted broker order without making any
external broker API call.

DRY_RUN means:
    - Phoenix produced a valid executable order.
    - The order would have been submitted.
    - No broker order was actually sent.
    - No market fill is assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionResult,
    OrderIntent,
)


@dataclass(frozen=True, slots=True)
class DryRunAuditRecord:
    """
    Immutable record of one simulated order submission.
    """

    intent_id: str

    signal_id: str

    security_id: str

    symbol: str

    quantity: int

    limit_price: float

    simulated_at: datetime


class DryRunExecutor:
    """
    Phoenix dry-run execution component.

    This component never calls a broker.
    """

    def __init__(self) -> None:
        self._records: list[
            DryRunAuditRecord
        ] = []

    def execute(
        self,
        *,
        intent: OrderIntent,
        executed_at: datetime,
    ) -> ExecutionResult:
        """
        Simulate broker submission.

        DRY_RUN returns OPEN rather than FILLED because
        Phoenix cannot assume that a live LIMIT order
        would actually fill.
        """

        record = DryRunAuditRecord(
            intent_id=(
                intent.intent_id.value
            ),
            signal_id=(
                intent.signal.signal_id.value
            ),
            security_id=(
                intent.selected_option.security_id
            ),
            symbol=(
                intent.selected_option.symbol
            ),
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            simulated_at=executed_at,
        )

        self._records.append(
            record
        )

        reference = BrokerOrderReference(
            broker_name="DRY_RUN",
            order_id=(
                "DRY-"
                f"{intent.intent_id.value}"
            ),
        )

        return ExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=reference,
            submitted_at=executed_at,
            message=(
                "DRY_RUN - no broker order submitted"
            ),
        )

    def records(
        self,
    ) -> tuple[
        DryRunAuditRecord,
        ...
    ]:
        """
        Return immutable dry-run audit history.
        """

        return tuple(
            self._records
        )

    def count(self) -> int:
        """
        Return number of simulated submissions.
        """

        return len(
            self._records
        )

    def clear(self) -> None:
        """
        Clear audit records.

        Intended for tests/session reset.
        """

        self._records.clear()