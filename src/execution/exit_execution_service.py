"""
Phoenix exit execution service.

Orchestrates broker-independent position exits.

Responsibilities:
    - Prevent duplicate SELL orders for one position.
    - Convert ExitPlan into ExitOrderIntent.
    - Simulate exits safely in DRY_RUN mode.
    - Route LIVE exits to ExitExecutionProvider only when
      the explicit live-exit safety gate is enabled.

No Dhan-specific payload structure belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import RLock

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
)
from src.execution.exit_execution_provider import (
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderIntent,
    ExitOrderIntentBuilder,
    ExitOrderIntentId,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
    IdempotencyKey,
    IdempotencyState,
)
from src.execution.position_exit_types import (
    ExitPlan,
)


class ExitExecutionDecision(str, Enum):
    ACCEPTED = "ACCEPTED"

    DUPLICATE_EXIT = "DUPLICATE_EXIT"

    LIVE_EXIT_DISABLED = "LIVE_EXIT_DISABLED"

    EXECUTION_FAILED = "EXECUTION_FAILED"


@dataclass(frozen=True, slots=True)
class ExitExecutionServiceResult:
    """
    Result of one Phoenix exit execution request.
    """

    accepted: bool

    decision: ExitExecutionDecision

    intent: ExitOrderIntent | None

    execution_result: ExitExecutionResult | None

    message: str | None = None

    @property
    def submitted(self) -> bool:
        return (
            self.execution_result is not None
            and self.execution_result.success
        )


class ExitExecutionService:
    """
    Main Phoenix exit-order orchestrator.

    LIVE SELL orders are disabled by default.

    Duplicate protection is based on FilledPositionId:

        one position
            ↓
        one active exit execution
    """

    def __init__(
        self,
        *,
        provider: ExitExecutionProvider,
        intent_builder: ExitOrderIntentBuilder | None = None,
        duplicate_guard: DuplicateOrderGuard | None = None,
        allow_live_exit_orders: bool = False,
    ) -> None:
        self._provider = provider

        self._intent_builder = (
            intent_builder
            or ExitOrderIntentBuilder()
        )

        self._duplicate_guard = (
            duplicate_guard
            or DuplicateOrderGuard()
        )

        self._allow_live_exit_orders = (
            allow_live_exit_orders
        )

        self._sequence = 0
        self._sequence_lock = RLock()

    @property
    def allow_live_exit_orders(self) -> bool:
        return self._allow_live_exit_orders

    @property
    def duplicate_guard(
        self,
    ) -> DuplicateOrderGuard:
        return self._duplicate_guard

    def execute(
        self,
        *,
        exit_plan: ExitPlan,
        execution_mode: ExecutionMode,
        requested_at: datetime,
    ) -> ExitExecutionServiceResult:
        """
        Execute one position exit request.
        """

        # --------------------------------------------------
        # Position-level duplicate protection
        # --------------------------------------------------

        key = self._idempotency_key(
            exit_plan
        )

        reservation = (
            self._duplicate_guard.reserve(
                key=key,
                created_at=requested_at,
            )
        )

        if not reservation.acquired:
            return ExitExecutionServiceResult(
                accepted=False,
                decision=(
                    ExitExecutionDecision
                    .DUPLICATE_EXIT
                ),
                intent=None,
                execution_result=None,
                message=(
                    "exit execution already exists "
                    "for this position"
                ),
            )

        # --------------------------------------------------
        # Build immutable SELL intent
        # --------------------------------------------------

        intent = self._intent_builder.build(
            intent_id=self._next_intent_id(
                requested_at
            ),
            exit_plan=exit_plan,
            created_at=requested_at,
        )

        self._duplicate_guard.attach_intent_id(
    key=key,
    intent_id=intent.intent_id.value,
    changed_at=requested_at,
)

        # --------------------------------------------------
        # DRY RUN
        # --------------------------------------------------

        if execution_mode is ExecutionMode.DRY_RUN:
            return self._execute_dry_run(
                key=key,
                intent=intent,
                requested_at=requested_at,
            )

        # --------------------------------------------------
        # LIVE safety gate
        # --------------------------------------------------

        if not self._allow_live_exit_orders:
            self._duplicate_guard.release(
                key=key,
                changed_at=requested_at,
            )

            return ExitExecutionServiceResult(
                accepted=False,
                decision=(
                    ExitExecutionDecision
                    .LIVE_EXIT_DISABLED
                ),
                intent=intent,
                execution_result=None,
                message=(
                    "LIVE exit execution is disabled "
                    "by Phoenix safety gate"
                ),
            )

        # --------------------------------------------------
        # LIVE submission
        #
        # Mark submitted BEFORE calling broker.
        #
        # If Dhan accepts the SELL but the network response
        # is lost, Phoenix must NOT automatically send
        # another SELL.
        # --------------------------------------------------

        self._duplicate_guard.mark_submitted(
            key=key,
            changed_at=requested_at,
        )

        try:
            result = self._provider.submit_exit(
                intent
            )

        except Exception as exc:
            # Do NOT release after broker submission attempt.
            # The broker may have accepted the order.
            return ExitExecutionServiceResult(
                accepted=False,
                decision=(
                    ExitExecutionDecision
                    .EXECUTION_FAILED
                ),
                intent=intent,
                execution_result=None,
                message=(
                    "exit broker submission failed: "
                    f"{exc}"
                ),
            )

        if (
            result.status
            is BrokerOrderStatus.FILLED
        ):
            self._duplicate_guard.mark_completed(
                key=key,
                changed_at=result.submitted_at,
            )

        return ExitExecutionServiceResult(
            accepted=True,
            decision=(
                ExitExecutionDecision.ACCEPTED
            ),
            intent=intent,
            execution_result=result,
            message=result.message,
        )

    def _execute_dry_run(
        self,
        *,
        key: IdempotencyKey,
        intent: ExitOrderIntent,
        requested_at: datetime,
    ) -> ExitExecutionServiceResult:
        """
        Simulate SELL submission.

        DRY_RUN returns OPEN rather than FILLED.
        """

        self._duplicate_guard.mark_submitted(
            key=key,
            changed_at=requested_at,
        )

        reference = BrokerOrderReference(
            broker_name="DRY_RUN",
            order_id=(
                f"DRY-{intent.intent_id.value}"
            ),
        )

        result = ExitExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=reference,
            submitted_at=requested_at,
            message=(
                "DRY_RUN - no broker SELL order submitted"
            ),
        )

        # A dry-run replay of the same position should not
        # create repeated simulated SELL orders.
        self._duplicate_guard.mark_completed(
            key=key,
            changed_at=requested_at,
        )

        return ExitExecutionServiceResult(
            accepted=True,
            decision=(
                ExitExecutionDecision.ACCEPTED
            ),
            intent=intent,
            execution_result=result,
            message=result.message,
        )

    @staticmethod
    def _idempotency_key(
        exit_plan: ExitPlan,
    ) -> IdempotencyKey:
        return IdempotencyKey(
            value=(
                "EXIT_POSITION:"
                f"{exit_plan.position_id.value}"
            )
        )

    def restore_sequence_floor(
        self,
        floor: int,
    ) -> int:
        """
        Restore the minimum already-consumed SELL intent
        sequence for the trading day.

        Recovery is monotonic and idempotent. It may advance
        the sequence but can never move it backwards.
        """

        if type(floor) is not int:
            raise TypeError(
                "sequence floor must be an integer"
            )

        if floor < 0:
            raise ValueError(
                "sequence floor cannot be negative"
            )

        with self._sequence_lock:
            self._sequence = max(
                self._sequence,
                floor,
            )

            return self._sequence

    def _next_intent_id(
        self,
        requested_at: datetime,
    ) -> ExitOrderIntentId:
        with self._sequence_lock:
            self._sequence += 1

            sequence = self._sequence

        return ExitOrderIntentId(
            "EXIT-"
            f"{requested_at.strftime('%Y%m%d')}-"
            f"{sequence:06d}"
        )
