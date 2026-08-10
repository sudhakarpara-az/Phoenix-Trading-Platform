"""
Phoenix exit reconciliation service.

Safely replaces an existing target SELL with the mandatory
session force-exit MARKET SELL.

Critical safety sequence:

    inspect existing exit
        ↓
    cancel if still active
        ↓
    CONFIRM cancellation
        ↓
    fetch final fill quantity
        ↓
    calculate remaining position
        ↓
    release existing exit idempotency lock
        ↓
    build force-exit plan for remaining quantity

This service does NOT directly submit the replacement SELL.
The resulting ExitPlan must pass through ExitExecutionService.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
)
from src.execution.exit_execution_provider import (
    ExitExecutionProvider,
    ExitOrderIntent,
    ExitOrderSnapshot,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
    IdempotencyKey,
    IdempotencyState,
)
from src.execution.position_exit_types import (
    ExitPlan,
    FilledPosition,
)


class ExitReconciliationDecision(str, Enum):
    """
    Result of force-exit reconciliation.
    """

    POSITION_ALREADY_CLOSED = (
        "POSITION_ALREADY_CLOSED"
    )

    FORCE_EXIT_READY = (
        "FORCE_EXIT_READY"
    )

    CANCELLATION_FAILED = (
        "CANCELLATION_FAILED"
    )

    CANCELLATION_NOT_CONFIRMED = (
        "CANCELLATION_NOT_CONFIRMED"
    )

    STATUS_UNKNOWN = (
        "STATUS_UNKNOWN"
    )

    INVALID_EXIT_REFERENCE = (
        "INVALID_EXIT_REFERENCE"
    )


@dataclass(frozen=True, slots=True)
class ExitReconciliationResult:
    """
    Result of reconciling an existing exit order.
    """

    decision: ExitReconciliationDecision

    original_quantity: int

    filled_quantity: int

    remaining_quantity: int

    force_exit_plan: ExitPlan | None

    final_snapshot: ExitOrderSnapshot | None

    message: str | None = None

    @property
    def force_exit_required(
        self,
    ) -> bool:
        return (
            self.decision
            is ExitReconciliationDecision
            .FORCE_EXIT_READY
            and self.force_exit_plan
            is not None
            and self.remaining_quantity > 0
        )


class ExitReconciliationService:
    """
    Reconciles an outstanding SELL before mandatory force exit.
    """

    _ACTIVE_STATUSES = {
        BrokerOrderStatus.PENDING,
        BrokerOrderStatus.OPEN,
        BrokerOrderStatus.PARTIALLY_FILLED,
    }

    def __init__(
        self,
        *,
        provider: ExitExecutionProvider,
        exit_plan_builder: ExitPlanBuilder,
        duplicate_guard: DuplicateOrderGuard,
    ) -> None:
        self._provider = provider
        self._exit_plan_builder = (
            exit_plan_builder
        )
        self._duplicate_guard = (
            duplicate_guard
        )

    def reconcile_for_force_exit(
        self,
        *,
        position: FilledPosition,
        active_exit_intent: ExitOrderIntent,
        broker_reference: BrokerOrderReference,
        requested_at: datetime,
    ) -> ExitReconciliationResult:
        """
        Reconcile an existing target/exit SELL before 15:15
        MARKET replacement.

        The replacement order itself is NOT submitted here.
        """

        # --------------------------------------------------
        # Reconciliation quantity scope
        #
        # FilledPosition.quantity is the historical/original
        # entry quantity.
        #
        # The active SELL may represent only the currently
        # open remainder after earlier partial exits.
        # --------------------------------------------------

        exit_quantity = (
            active_exit_intent.quantity
        )

        if (
            exit_quantity
            > position.quantity
        ):
            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .INVALID_EXIT_REFERENCE
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=0,
                remaining_quantity=(
                    exit_quantity
                ),
                force_exit_plan=None,
                final_snapshot=None,
                message=(
                    "active exit quantity exceeds "
                    "supplied position quantity"
                ),
            )

        if (
            active_exit_intent.position_id
            != position.position_id
        ):
            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .INVALID_EXIT_REFERENCE
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=0,
                remaining_quantity=(
                    exit_quantity
                ),
                force_exit_plan=None,
                final_snapshot=None,
                message=(
                    "active exit intent does not belong "
                    "to supplied position"
                ),
            )

        key = self._exit_key(
            position
        )

        # --------------------------------------------------
        # Inspect current broker state
        # --------------------------------------------------

        try:
            snapshot = (
                self._provider.get_exit_status(
                    broker_reference
                )
            )
        except Exception as exc:
            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .STATUS_UNKNOWN
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=0,
                remaining_quantity=(
                    exit_quantity
                ),
                force_exit_plan=None,
                final_snapshot=None,
                message=(
                    "failed to fetch active exit status: "
                    f"{exc}"
                ),
            )

        # --------------------------------------------------
        # Broker snapshot identity / quantity validation
        # --------------------------------------------------

        if (
            snapshot.quantity
            != exit_quantity
            or snapshot.filled_quantity
            > exit_quantity
            or (
                snapshot.status
                is BrokerOrderStatus.FILLED
                and snapshot.filled_quantity
                != exit_quantity
            )
        ):
            filled_quantity = min(
                snapshot.filled_quantity,
                exit_quantity,
            )

            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .INVALID_EXIT_REFERENCE
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    filled_quantity
                ),
                remaining_quantity=(
                    max(
                        exit_quantity
                        - filled_quantity,
                        0,
                    )
                ),
                force_exit_plan=None,
                final_snapshot=snapshot,
                message=(
                    "broker exit snapshot quantity "
                    "does not match active exit intent"
                ),
            )

        # --------------------------------------------------
        # Existing exit already fully filled
        # --------------------------------------------------

        if (
            snapshot.status
            is BrokerOrderStatus.FILLED
        ):
            self._complete_guard_if_needed(
                key=key,
                changed_at=requested_at,
            )

            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .POSITION_ALREADY_CLOSED
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    exit_quantity
                ),
                remaining_quantity=0,
                force_exit_plan=None,
                final_snapshot=snapshot,
                message=(
                    "existing exit order is already filled"
                ),
            )

        # --------------------------------------------------
        # Already cancelled before reconciliation
        # --------------------------------------------------

        if (
            snapshot.status
            is BrokerOrderStatus.CANCELLED
        ):
            return self._build_replacement_after_cancel(
                position=position,
                snapshot=snapshot,
                key=key,
                requested_at=requested_at,
            )

        # --------------------------------------------------
        # Unknown/rejected state cannot safely trigger
        # another SELL automatically.
        # --------------------------------------------------

        if (
            snapshot.status
            not in self._ACTIVE_STATUSES
        ):
            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .STATUS_UNKNOWN
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    min(
                        snapshot.filled_quantity,
                        exit_quantity,
                    )
                ),
                remaining_quantity=(
                    max(
                        exit_quantity
                        - snapshot.filled_quantity,
                        0,
                    )
                ),
                force_exit_plan=None,
                final_snapshot=snapshot,
                message=(
                    "existing exit order is not in a "
                    "safe replaceable state"
                ),
            )

        # --------------------------------------------------
        # Cancel active target/exit order
        # --------------------------------------------------

        try:
            cancellation = (
                self._provider.cancel_exit(
                    broker_reference
                )
            )
        except Exception as exc:
            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .CANCELLATION_FAILED
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    snapshot.filled_quantity
                ),
                remaining_quantity=(
                    max(
                        exit_quantity
                        - snapshot.filled_quantity,
                        0,
                    )
                ),
                force_exit_plan=None,
                final_snapshot=snapshot,
                message=(
                    "failed to cancel active exit: "
                    f"{exc}"
                ),
            )

        if (
            not cancellation.success
            or cancellation.status
            is not BrokerOrderStatus.CANCELLED
        ):
            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .CANCELLATION_FAILED
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    snapshot.filled_quantity
                ),
                remaining_quantity=(
                    max(
                        exit_quantity
                        - snapshot.filled_quantity,
                        0,
                    )
                ),
                force_exit_plan=None,
                final_snapshot=snapshot,
                message=(
                    cancellation.message
                    or (
                        "broker did not confirm "
                        "exit cancellation"
                    )
                ),
            )

        # --------------------------------------------------
        # Critical race protection:
        #
        # Query AGAIN after cancellation because additional
        # fills may have occurred while cancellation was
        # being processed.
        # --------------------------------------------------

        try:
            final_snapshot = (
                self._provider.get_exit_status(
                    broker_reference
                )
            )
        except Exception as exc:
            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .CANCELLATION_NOT_CONFIRMED
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    snapshot.filled_quantity
                ),
                remaining_quantity=(
                    max(
                        exit_quantity
                        - snapshot.filled_quantity,
                        0,
                    )
                ),
                force_exit_plan=None,
                final_snapshot=snapshot,
                message=(
                    "unable to confirm final exit state "
                    "after cancellation: "
                    f"{exc}"
                ),
            )

        if (
            final_snapshot.quantity
            != exit_quantity
            or final_snapshot.filled_quantity
            > exit_quantity
            or (
                final_snapshot.status
                is BrokerOrderStatus.FILLED
                and final_snapshot.filled_quantity
                != exit_quantity
            )
        ):
            filled_quantity = min(
                final_snapshot.filled_quantity,
                exit_quantity,
            )

            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .INVALID_EXIT_REFERENCE
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    filled_quantity
                ),
                remaining_quantity=(
                    max(
                        exit_quantity
                        - filled_quantity,
                        0,
                    )
                ),
                force_exit_plan=None,
                final_snapshot=(
                    final_snapshot
                ),
                message=(
                    "final broker exit snapshot quantity "
                    "does not match active exit intent"
                ),
            )

        if (
            final_snapshot.status
            is BrokerOrderStatus.FILLED
        ):
            self._complete_guard_if_needed(
                key=key,
                changed_at=requested_at,
            )

            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .POSITION_ALREADY_CLOSED
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    exit_quantity
                ),
                remaining_quantity=0,
                force_exit_plan=None,
                final_snapshot=final_snapshot,
                message=(
                    "exit filled during cancellation race"
                ),
            )

        if (
            final_snapshot.status
            is not BrokerOrderStatus.CANCELLED
        ):
            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .CANCELLATION_NOT_CONFIRMED
                ),
                original_quantity=(
                    exit_quantity
                ),
                filled_quantity=(
                    min(
                        final_snapshot.filled_quantity,
                        exit_quantity,
                    )
                ),
                remaining_quantity=(
                    max(
                        exit_quantity
                        - final_snapshot.filled_quantity,
                        0,
                    )
                ),
                force_exit_plan=None,
                final_snapshot=final_snapshot,
                message=(
                    "exit cancellation is not confirmed"
                ),
            )

        return self._build_replacement_after_cancel(
            position=position,
            snapshot=final_snapshot,
            key=key,
            requested_at=requested_at,
        )

    def _build_replacement_after_cancel(
        self,
        *,
        position: FilledPosition,
        snapshot: ExitOrderSnapshot,
        key: IdempotencyKey,
        requested_at: datetime,
    ) -> ExitReconciliationResult:
        filled_quantity = min(
            snapshot.filled_quantity,
            snapshot.quantity,
        )

        remaining_quantity = max(
            snapshot.quantity
            - filled_quantity,
            0,
        )

        if remaining_quantity == 0:
            self._complete_guard_if_needed(
                key=key,
                changed_at=requested_at,
            )

            return ExitReconciliationResult(
                decision=(
                    ExitReconciliationDecision
                    .POSITION_ALREADY_CLOSED
                ),
                original_quantity=(
                    snapshot.quantity
                ),
                filled_quantity=(
                    filled_quantity
                ),
                remaining_quantity=0,
                force_exit_plan=None,
                final_snapshot=snapshot,
            )

        # Existing SELL is now confirmed dead.
        # It is finally safe to release the position exit key.
        self._release_reconciled_guard(
            key=key,
            changed_at=requested_at,
        )

        force_exit_plan = (
            self._exit_plan_builder
            .build_force_exit(
                position=position,
                created_at=requested_at,
                quantity=remaining_quantity,
            )
        )

        return ExitReconciliationResult(
            decision=(
                ExitReconciliationDecision
                .FORCE_EXIT_READY
            ),
            original_quantity=(
                snapshot.quantity
            ),
            filled_quantity=(
                filled_quantity
            ),
            remaining_quantity=(
                remaining_quantity
            ),
            force_exit_plan=force_exit_plan,
            final_snapshot=snapshot,
            message=(
                "existing exit cancelled and "
                "force-exit replacement is ready"
            ),
        )

    def _release_reconciled_guard(
        self,
        *,
        key: IdempotencyKey,
        changed_at: datetime,
    ) -> None:
        record = self._duplicate_guard.get(
            key
        )

        if record is None:
            return

        if (
            record.state
            is IdempotencyState.SUBMITTED
        ):
            self._duplicate_guard\
                .release_after_reconciliation(
                    key=key,
                    changed_at=changed_at,
                )

    def _complete_guard_if_needed(
        self,
        *,
        key: IdempotencyKey,
        changed_at: datetime,
    ) -> None:
        record = self._duplicate_guard.get(
            key
        )

        if record is None:
            return

        if record.state in {
            IdempotencyState.RESERVED,
            IdempotencyState.SUBMITTED,
        }:
            self._duplicate_guard.mark_completed(
                key=key,
                changed_at=changed_at,
            )

    @staticmethod
    def _exit_key(
        position: FilledPosition,
    ) -> IdempotencyKey:
        return IdempotencyKey(
            value=(
                "EXIT_POSITION:"
                f"{position.position_id.value}"
            )
        )
