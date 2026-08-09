"""
Phoenix M07 mandatory session force-exit coordinator.

Determines the safe action for every managed position at the
mandatory intraday exit time.

Responsibilities:
    - Determine whether force-exit time has been reached.
    - Inspect all positions retaining open quantity.
    - Request a fresh FORCE_EXIT for positions without an
      existing exit.
    - Route EXIT_PENDING / RECONCILIATION_REQUIRED positions
      toward broker reconciliation instead of generating a
      duplicate SELL.
    - Ignore fully closed positions.

This component does NOT:
    - call Dhan
    - cancel orders
    - submit SELL orders
    - perform M06 broker reconciliation directly

Those responsibilities remain in M06.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    RiskTriggerType,
)


class ForceExitAction(str, Enum):
    """
    Safe action determined for one managed position.
    """

    NONE = "NONE"

    NEW_FORCE_EXIT = "NEW_FORCE_EXIT"

    RECONCILE_EXISTING_EXIT = (
        "RECONCILE_EXISTING_EXIT"
    )


class ForceExitReason(str, Enum):
    """
    Explanation for one force-exit coordination result.
    """

    BEFORE_FORCE_EXIT_TIME = (
        "BEFORE_FORCE_EXIT_TIME"
    )

    POSITION_CLOSED = "POSITION_CLOSED"

    OPEN_POSITION = "OPEN_POSITION"

    PARTIAL_POSITION = "PARTIAL_POSITION"

    EXIT_ALREADY_PENDING = (
        "EXIT_ALREADY_PENDING"
    )

    RECONCILIATION_ALREADY_REQUIRED = (
        "RECONCILIATION_ALREADY_REQUIRED"
    )


@dataclass(frozen=True, slots=True)
class ForceExitInstruction:
    """
    Safe session-close action for one managed position.
    """

    position_id: FilledPositionId

    action: ForceExitAction

    reason: ForceExitReason

    trigger: RiskTriggerType

    quantity: int

    evaluated_at: datetime

    @property
    def force_exit_required(self) -> bool:
        return (
            self.action
            is ForceExitAction.NEW_FORCE_EXIT
            and self.trigger
            is RiskTriggerType.FORCE_EXIT
            and self.quantity > 0
        )

    @property
    def reconciliation_required(self) -> bool:
        return (
            self.action
            is ForceExitAction
            .RECONCILE_EXISTING_EXIT
        )


@dataclass(frozen=True, slots=True)
class ForceExitBatch:
    """
    Result of evaluating all registered M07 positions.
    """

    force_exit_time_reached: bool

    instructions: tuple[
        ForceExitInstruction,
        ...
    ]

    evaluated_at: datetime

    @property
    def new_force_exits(
        self,
    ) -> tuple[
        ForceExitInstruction,
        ...
    ]:
        return tuple(
            instruction
            for instruction in self.instructions
            if instruction.force_exit_required
        )

    @property
    def reconciliations(
        self,
    ) -> tuple[
        ForceExitInstruction,
        ...
    ]:
        return tuple(
            instruction
            for instruction in self.instructions
            if instruction.reconciliation_required
        )


class ForceExitCoordinator:
    """
    Coordinates mandatory intraday position closure.

    Default Phoenix force-exit time:
        15:15

    A new SELL is requested only for a position that does not
    already have an exit/reconciliation in progress.
    """

    def __init__(
        self,
        *,
        registry: PositionRegistry,
        force_exit_time: time = time(
            hour=15,
            minute=15,
        ),
    ) -> None:
        self._registry = registry
        self._force_exit_time = (
            force_exit_time
        )

    @property
    def force_exit_time(
        self,
    ) -> time:
        return self._force_exit_time

    def is_force_exit_time(
        self,
        now: datetime,
    ) -> bool:
        """
        True at or after the configured mandatory exit time.
        """

        return (
            now.time()
            >= self._force_exit_time
        )

    def evaluate_position(
        self,
        *,
        position: ManagedPosition,
        evaluated_at: datetime,
    ) -> ForceExitInstruction:
        """
        Determine the safe force-exit action for one position.
        """

        if not self.is_force_exit_time(
            evaluated_at
        ):
            return ForceExitInstruction(
                position_id=position.position_id,
                action=ForceExitAction.NONE,
                reason=(
                    ForceExitReason
                    .BEFORE_FORCE_EXIT_TIME
                ),
                trigger=RiskTriggerType.NONE,
                quantity=position.open_quantity,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # No exposure remains.
        # --------------------------------------------------

        if (
            position.state
            is ManagedPositionState.CLOSED
            or position.open_quantity <= 0
        ):
            return ForceExitInstruction(
                position_id=position.position_id,
                action=ForceExitAction.NONE,
                reason=(
                    ForceExitReason
                    .POSITION_CLOSED
                ),
                trigger=RiskTriggerType.NONE,
                quantity=0,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Existing SELL/order lifecycle already in progress.
        #
        # Never generate another SELL directly.
        # --------------------------------------------------

        if (
            position.state
            is ManagedPositionState.EXIT_PENDING
        ):
            return ForceExitInstruction(
                position_id=position.position_id,
                action=(
                    ForceExitAction
                    .RECONCILE_EXISTING_EXIT
                ),
                reason=(
                    ForceExitReason
                    .EXIT_ALREADY_PENDING
                ),
                trigger=RiskTriggerType.FORCE_EXIT,
                quantity=position.open_quantity,
                evaluated_at=evaluated_at,
            )

        if (
            position.state
            is ManagedPositionState
            .RECONCILIATION_REQUIRED
        ):
            return ForceExitInstruction(
                position_id=position.position_id,
                action=(
                    ForceExitAction
                    .RECONCILE_EXISTING_EXIT
                ),
                reason=(
                    ForceExitReason
                    .RECONCILIATION_ALREADY_REQUIRED
                ),
                trigger=RiskTriggerType.FORCE_EXIT,
                quantity=position.open_quantity,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Partial position:
        # sell ONLY remaining open quantity.
        # --------------------------------------------------

        if (
            position.state
            is ManagedPositionState.PARTIALLY_EXITED
        ):
            return ForceExitInstruction(
                position_id=position.position_id,
                action=(
                    ForceExitAction.NEW_FORCE_EXIT
                ),
                reason=(
                    ForceExitReason.PARTIAL_POSITION
                ),
                trigger=RiskTriggerType.FORCE_EXIT,
                quantity=position.open_quantity,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Normal open position.
        # --------------------------------------------------

        return ForceExitInstruction(
            position_id=position.position_id,
            action=ForceExitAction.NEW_FORCE_EXIT,
            reason=ForceExitReason.OPEN_POSITION,
            trigger=RiskTriggerType.FORCE_EXIT,
            quantity=position.open_quantity,
            evaluated_at=evaluated_at,
        )

    def evaluate_all(
        self,
        *,
        evaluated_at: datetime,
    ) -> ForceExitBatch:
        """
        Evaluate all registered positions.

        Before force-exit time, every position may be represented
        with action NONE.

        At/after force-exit time, only actual open exposure
        produces NEW_FORCE_EXIT or reconciliation instructions.
        """

        positions = self._registry.all()

        instructions = tuple(
            self.evaluate_position(
                position=position,
                evaluated_at=evaluated_at,
            )
            for position in positions
        )

        return ForceExitBatch(
            force_exit_time_reached=(
                self.is_force_exit_time(
                    evaluated_at
                )
            ),
            instructions=instructions,
            evaluated_at=evaluated_at,
        )