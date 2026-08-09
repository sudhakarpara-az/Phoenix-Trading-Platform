"""
Phoenix M07 position exit decision engine.

Combines:
    - managed position state
    - target-trigger result
    - stop-loss-trigger result
    - mandatory force-exit condition

into one deterministic exit decision.

Priority:
    CLOSED
        -> NONE

    FORCE EXIT
        -> FORCE_EXIT

    STOP LOSS
        -> STOP_LOSS

    TARGET
        -> TARGET

    otherwise
        -> NONE

No broker execution belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    RiskTriggerType,
)
from src.risk.stop_loss_trigger_monitor import (
    StopLossTriggerResult,
)
from src.risk.target_trigger_monitor import (
    TargetTriggerResult,
)


class PositionExitDecisionStatus(str, Enum):
    """
    Outcome of one exit-decision evaluation.
    """

    NO_EXIT = "NO_EXIT"

    EXIT_REQUIRED = "EXIT_REQUIRED"

    POSITION_CLOSED = "POSITION_CLOSED"

    EXIT_ALREADY_PENDING = "EXIT_ALREADY_PENDING"

    RECONCILIATION_REQUIRED = (
        "RECONCILIATION_REQUIRED"
    )


@dataclass(frozen=True, slots=True)
class PositionExitDecision:
    """
    Final M07 exit decision for one managed position.
    """

    status: PositionExitDecisionStatus

    position_id: FilledPositionId

    trigger: RiskTriggerType

    quantity: int

    decided_at: datetime

    message: str | None = None

    @property
    def exit_required(self) -> bool:
        return (
            self.status
            is PositionExitDecisionStatus.EXIT_REQUIRED
            and self.trigger
            is not RiskTriggerType.NONE
            and self.quantity > 0
        )


class PositionExitDecisionEngine:
    """
    Deterministic M07 exit-priority engine.
    """

    def decide(
        self,
        *,
        position: ManagedPosition,
        target_result: TargetTriggerResult | None,
        stop_result: StopLossTriggerResult | None,
        force_exit: bool,
        decided_at: datetime,
    ) -> PositionExitDecision:
        """
        Determine whether M07 requires an exit.

        Exit priority:

            1. position closed
            2. reconciliation required
            3. existing exit pending
            4. mandatory force exit
            5. stop loss
            6. target
            7. no exit
        """

        # --------------------------------------------------
        # No open quantity means there is nothing to sell.
        # --------------------------------------------------

        if (
            position.state
            is ManagedPositionState.CLOSED
            or position.open_quantity <= 0
        ):
            return PositionExitDecision(
                status=(
                    PositionExitDecisionStatus
                    .POSITION_CLOSED
                ),
                position_id=position.position_id,
                trigger=RiskTriggerType.NONE,
                quantity=0,
                decided_at=decided_at,
                message=(
                    "position has no open quantity"
                ),
            )

        # --------------------------------------------------
        # Reconciliation must be resolved before another exit.
        # --------------------------------------------------

        if (
            position.state
            is ManagedPositionState
            .RECONCILIATION_REQUIRED
        ):
            return PositionExitDecision(
                status=(
                    PositionExitDecisionStatus
                    .RECONCILIATION_REQUIRED
                ),
                position_id=position.position_id,
                trigger=RiskTriggerType.NONE,
                quantity=position.open_quantity,
                decided_at=decided_at,
                message=(
                    "position requires exit reconciliation"
                ),
            )

        # --------------------------------------------------
        # Do not generate another exit while one is pending.
        # --------------------------------------------------

        if (
            position.state
            is ManagedPositionState.EXIT_PENDING
        ):
            return PositionExitDecision(
                status=(
                    PositionExitDecisionStatus
                    .EXIT_ALREADY_PENDING
                ),
                position_id=position.position_id,
                trigger=RiskTriggerType.NONE,
                quantity=position.open_quantity,
                decided_at=decided_at,
                message=(
                    "position already has an exit pending"
                ),
            )

        # --------------------------------------------------
        # Highest actionable priority: mandatory force exit.
        # --------------------------------------------------

        if force_exit:
            return self._exit_required(
                position=position,
                trigger=RiskTriggerType.FORCE_EXIT,
                decided_at=decided_at,
                message=(
                    "mandatory session force exit required"
                ),
            )

        # --------------------------------------------------
        # Stop-loss outranks target.
        # --------------------------------------------------

        if (
            stop_result is not None
            and stop_result.triggered
        ):
            self._validate_result_position(
                position=position,
                result_position_id=(
                    stop_result.position_id
                ),
                source="stop-loss",
            )

            return self._exit_required(
                position=position,
                trigger=RiskTriggerType.STOP_LOSS,
                decided_at=decided_at,
                message=(
                    "stop-loss trigger reached"
                ),
            )

        # --------------------------------------------------
        # Target exit.
        # --------------------------------------------------

        if (
            target_result is not None
            and target_result.triggered
        ):
            self._validate_result_position(
                position=position,
                result_position_id=(
                    target_result.position_id
                ),
                source="target",
            )

            return self._exit_required(
                position=position,
                trigger=RiskTriggerType.TARGET,
                decided_at=decided_at,
                message=(
                    "target trigger reached"
                ),
            )

        return PositionExitDecision(
            status=(
                PositionExitDecisionStatus.NO_EXIT
            ),
            position_id=position.position_id,
            trigger=RiskTriggerType.NONE,
            quantity=position.open_quantity,
            decided_at=decided_at,
            message=None,
        )

    @staticmethod
    def _exit_required(
        *,
        position: ManagedPosition,
        trigger: RiskTriggerType,
        decided_at: datetime,
        message: str,
    ) -> PositionExitDecision:
        return PositionExitDecision(
            status=(
                PositionExitDecisionStatus
                .EXIT_REQUIRED
            ),
            position_id=position.position_id,
            trigger=trigger,
            quantity=position.open_quantity,
            decided_at=decided_at,
            message=message,
        )

    @staticmethod
    def _validate_result_position(
        *,
        position: ManagedPosition,
        result_position_id: FilledPositionId,
        source: str,
    ) -> None:
        if (
            result_position_id
            != position.position_id
        ):
            raise ValueError(
                f"{source} trigger result does not belong "
                "to managed position"
            )