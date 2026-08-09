"""
Phoenix M07 -> M06 exit integration service.

Formal handoff from:

    M07 PositionExitDecision
        ->
    M06 ExitPlan / ExitExecutionService

Responsibilities:
    - Validate that an M07 decision belongs to the position.
    - Validate remaining exit quantity.
    - Translate TARGET / STOP_LOSS / FORCE_EXIT decisions
      into existing M06 ExitPlan models.
    - Move the M07 position to EXIT_PENDING before submission.
    - Delegate all actual SELL execution to M06.
    - Preserve M06 duplicate/idempotency protections.
    - Move uncertain/rejected submissions into
      RECONCILIATION_REQUIRED.

No broker API calls belong directly in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.execution.execution_types import (
    ExecutionMode,
)
from src.execution.exit_execution_service import (
    ExitExecutionService,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitPlan,
    ExitReason,
)
from src.risk.position_exit_decision_engine import (
    PositionExitDecision,
    PositionExitDecisionStatus,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    RiskTriggerType,
)


class M07ExitIntegrationStatus(str, Enum):
    NO_EXIT = "NO_EXIT"

    SUBMITTED = "SUBMITTED"

    RECONCILIATION_REQUIRED = (
        "RECONCILIATION_REQUIRED"
    )


@dataclass(frozen=True, slots=True)
class M07ExitIntegrationResult:
    status: M07ExitIntegrationStatus

    position: ManagedPosition

    exit_plan: ExitPlan | None

    execution_result: object | None

    message: str | None = None

    @property
    def submitted(self) -> bool:
        return (
            self.status
            is M07ExitIntegrationStatus.SUBMITTED
        )


class M07ToM06ExitIntegrationService:
    """
    Bridges M07 risk decisions into M06 exit execution.
    """

    def __init__(
        self,
        *,
        registry: PositionRegistry,
        lifecycle_manager: PositionLifecycleManager,
        exit_plan_builder: ExitPlanBuilder,
        exit_execution_service: ExitExecutionService,
    ) -> None:
        self._registry = registry
        self._lifecycle_manager = (
            lifecycle_manager
        )
        self._exit_plan_builder = (
            exit_plan_builder
        )
        self._exit_execution_service = (
            exit_execution_service
        )

    def execute_decision(
        self,
        *,
        decision: PositionExitDecision,
        execution_mode: ExecutionMode,
        requested_at: datetime,
    ) -> M07ExitIntegrationResult:
        """
        Execute one actionable M07 exit decision through M06.
        """

        position = self._registry.require(
            decision.position_id
        )

        # --------------------------------------------------
        # Non-actionable decision.
        # --------------------------------------------------

        if (
            decision.status
            is not PositionExitDecisionStatus.EXIT_REQUIRED
            or not decision.exit_required
        ):
            return M07ExitIntegrationResult(
                status=(
                    M07ExitIntegrationStatus.NO_EXIT
                ),
                position=position,
                exit_plan=None,
                execution_result=None,
                message=(
                    "M07 decision does not require an exit"
                ),
            )

        # --------------------------------------------------
        # Identity / quantity protection.
        # --------------------------------------------------

        if (
            decision.position_id
            != position.position_id
        ):
            raise ValueError(
                "exit decision does not belong to "
                "managed position"
            )

        if decision.quantity <= 0:
            raise ValueError(
                "exit decision quantity must be "
                "greater than zero"
            )

        if (
            decision.quantity
            != position.open_quantity
        ):
            raise ValueError(
                "exit decision quantity must equal "
                "managed position open quantity"
            )

        if (
            decision.trigger
            is RiskTriggerType.NONE
        ):
            raise ValueError(
                "actionable exit decision requires "
                "exit trigger"
            )

        # --------------------------------------------------
        # Build M06 ExitPlan BEFORE changing lifecycle state.
        #
        # This allows deterministic model/configuration
        # failures to occur without changing the registry.
        # --------------------------------------------------

        exit_plan = self._build_exit_plan(
            position=position,
            decision=decision,
            created_at=requested_at,
        )

        # --------------------------------------------------
        # Lock M07 lifecycle before broker submission.
        #
        # This prevents another M07 evaluation from creating
        # a competing SELL during the broker call.
        # --------------------------------------------------

        pending_position = (
            self._lifecycle_manager
            .mark_exit_pending(
                position_id=position.position_id,
                trigger=decision.trigger,
                changed_at=requested_at,
            )
        )

        # --------------------------------------------------
        # Actual SELL execution remains entirely in M06.
        # --------------------------------------------------

        result = (
            self._exit_execution_service.execute(
                exit_plan=exit_plan,
                execution_mode=execution_mode,
                requested_at=requested_at,
            )
        )

        if result.accepted:
            return M07ExitIntegrationResult(
                status=(
                    M07ExitIntegrationStatus.SUBMITTED
                ),
                position=pending_position,
                exit_plan=exit_plan,
                execution_result=result,
                message=None,
            )

        # --------------------------------------------------
        # Conservative failure handling.
        #
        # We do NOT automatically return to OPEN.
        #
        # M06 may have:
        #   - attempted broker submission
        #   - detected an existing idempotency reservation
        #   - received an ambiguous broker failure
        #
        # All of those require reconciliation before another
        # SELL can safely be generated.
        # --------------------------------------------------

        reconciliation_position = (
            self._lifecycle_manager
            .mark_reconciliation_required(
                position_id=position.position_id,
                changed_at=requested_at,
            )
        )

        return M07ExitIntegrationResult(
            status=(
                M07ExitIntegrationStatus
                .RECONCILIATION_REQUIRED
            ),
            position=reconciliation_position,
            exit_plan=exit_plan,
            execution_result=result,
            message=(
                "M06 exit was not accepted; broker/order "
                "state must be reconciled before retry"
            ),
        )

    def _build_exit_plan(
        self,
        *,
        position: ManagedPosition,
        decision: PositionExitDecision,
        created_at: datetime,
    ) -> ExitPlan:
        """
        Translate M07 trigger into existing M06 exit model.
        """

        if (
            decision.trigger
            is RiskTriggerType.TARGET
        ):
            if position.target is None:
                raise ValueError(
                    "TARGET exit requires mapped "
                    "option target"
                )

            return (
                self._exit_plan_builder
                .build_target_exit(
                    position=position.position,
                    mapped_target_price=(
                        position.target
                        .mapped_target_price
                    ),
                    created_at=created_at,
                )
            )

        if (
            decision.trigger
            is RiskTriggerType.FORCE_EXIT
        ):
            return (
                self._exit_plan_builder
                .build_force_exit(
                    position=position.position,
                    quantity=decision.quantity,
                    created_at=created_at,
                )
            )

        if (
            decision.trigger
            is RiskTriggerType.STOP_LOSS
        ):
            if position.stop_loss is None:
                raise ValueError(
                    "STOP_LOSS exit requires configured "
                    "stop loss"
                )

            return ExitPlan(
                position_id=position.position_id,
                security_id=position.security_id,
                symbol=position.symbol,
                option_type=(
                    position.position.option_type
                ),
                quantity=decision.quantity,
                reason=ExitReason.STOP_LOSS,
                order_type=ExitOrderType.MARKET,
                mapped_target_price=None,
                target_plan=None,
                exit_price=None,
                created_at=created_at,
            )

        raise ValueError(
            "unsupported M07 exit trigger"
        )