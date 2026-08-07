"""
Phoenix M07 position lifecycle manager.

Owns controlled transitions of immutable ManagedPosition snapshots.

Responsibilities:
    - OPEN/PARTIALLY_EXITED -> EXIT_PENDING
    - mark target or stop state as TRIGGERED
    - apply executed SELL fills
    - update open / closed quantity
    - update realized P&L
    - move partial exits to PARTIALLY_EXITED
    - move fully exited positions to CLOSED
    - mark broker-uncertain positions as RECONCILIATION_REQUIRED
    - restore a reconciled position to OPEN/PARTIALLY_EXITED

PositionRegistry remains the storage authority.

No broker API or SELL submission belongs here.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from math import isfinite

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
    StopLossState,
    TargetState,
)


class PositionLifecycleManager:
    """
    Controlled state-transition service for M07 positions.
    """

    def __init__(
        self,
        *,
        registry: PositionRegistry,
    ) -> None:
        self._registry = registry

    def mark_exit_pending(
        self,
        *,
        position_id: FilledPositionId,
        trigger: RiskTriggerType,
        changed_at: datetime,
    ) -> ManagedPosition:
        """
        Mark a managed position as having an exit in progress.

        TARGET:
            target state becomes TRIGGERED.

        STOP_LOSS:
            stop-loss state becomes TRIGGERED.

        FORCE_EXIT / MANUAL:
            stop and target definitions remain unchanged.
        """

        position = self._registry.require(
            position_id
        )

        if position.open_quantity <= 0:
            raise ValueError(
                "cannot mark closed position as EXIT_PENDING"
            )

        if (
            position.state
            is ManagedPositionState.CLOSED
        ):
            raise ValueError(
                "cannot mark closed position as EXIT_PENDING"
            )

        if (
            position.state
            is ManagedPositionState.EXIT_PENDING
        ):
            raise RuntimeError(
                "position already has an exit pending"
            )

        if (
            position.state
            is ManagedPositionState
            .RECONCILIATION_REQUIRED
        ):
            raise RuntimeError(
                "position requires reconciliation before "
                "new exit can be marked pending"
            )

        if trigger is RiskTriggerType.NONE:
            raise ValueError(
                "exit pending requires actionable trigger"
            )

        stop_loss = position.stop_loss
        target = position.target

        if trigger is RiskTriggerType.STOP_LOSS:
            if stop_loss is None:
                raise ValueError(
                    "STOP_LOSS exit requires configured stop loss"
                )

            stop_loss = replace(
                stop_loss,
                state=StopLossState.TRIGGERED,
            )

        elif trigger is RiskTriggerType.TARGET:
            if target is None:
                raise ValueError(
                    "TARGET exit requires configured target"
                )

            target = replace(
                target,
                state=TargetState.TRIGGERED,
            )

        updated = replace(
            position,
            state=ManagedPositionState.EXIT_PENDING,
            stop_loss=stop_loss,
            target=target,
            updated_at=changed_at,
        )

        return self._registry.replace(
            updated
        )

    def apply_exit_fill(
        self,
        *,
        position_id: FilledPositionId,
        fill_quantity: int,
        fill_price: float,
        filled_at: datetime,
    ) -> ManagedPosition:
        """
        Apply one executed SELL fill.

        Realized P&L:

            (fill_price - actual_entry_price)
            * fill_quantity

        Partial:
            open_quantity > 0
            -> PARTIALLY_EXITED

        Full:
            open_quantity == 0
            -> CLOSED
        """

        position = self._registry.require(
            position_id
        )

        if fill_quantity <= 0:
            raise ValueError(
                "exit fill quantity must be greater than zero"
            )

        if not isfinite(
            fill_price
        ):
            raise ValueError(
                "exit fill price must be finite"
            )

        if fill_price <= 0:
            raise ValueError(
                "exit fill price must be greater than zero"
            )

        if position.open_quantity <= 0:
            raise ValueError(
                "cannot apply exit fill to closed position"
            )

        if fill_quantity > position.open_quantity:
            raise ValueError(
                "exit fill quantity cannot exceed "
                "open position quantity"
            )

        realized_for_fill = (
            fill_price
            - position.entry_price
        ) * fill_quantity

        new_closed_quantity = (
            position.closed_quantity
            + fill_quantity
        )

        new_open_quantity = (
            position.open_quantity
            - fill_quantity
        )

        new_realized_pnl = (
            position.realized_pnl
            + realized_for_fill
        )

        if new_open_quantity == 0:
            new_state = (
                ManagedPositionState.CLOSED
            )
        else:
            new_state = (
                ManagedPositionState
                .PARTIALLY_EXITED
            )

        updated = replace(
            position,
            open_quantity=new_open_quantity,
            closed_quantity=new_closed_quantity,
            realized_pnl=new_realized_pnl,
            state=new_state,
            updated_at=filled_at,
        )

        return self._registry.replace(
            updated
        )

    def mark_reconciliation_required(
        self,
        *,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> ManagedPosition:
        """
        Mark position as requiring broker reconciliation.

        Used when Phoenix cannot prove whether a SELL has
        filled, remained open, or failed.
        """

        position = self._registry.require(
            position_id
        )

        if position.open_quantity <= 0:
            raise ValueError(
                "closed position does not require reconciliation"
            )

        if (
            position.state
            is ManagedPositionState.CLOSED
        ):
            raise ValueError(
                "closed position does not require reconciliation"
            )

        updated = replace(
            position,
            state=(
                ManagedPositionState
                .RECONCILIATION_REQUIRED
            ),
            updated_at=changed_at,
        )

        return self._registry.replace(
            updated
        )

    def restore_after_reconciliation(
        self,
        *,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> ManagedPosition:
        """
        Restore position after reconciliation confirms that no
        active exit remains and open quantity still exists.

        State becomes:

            OPEN
                when nothing has been closed

            PARTIALLY_EXITED
                when some quantity was already closed
        """

        position = self._registry.require(
            position_id
        )

        if (
            position.state
            not in {
                ManagedPositionState.EXIT_PENDING,
                ManagedPositionState.RECONCILIATION_REQUIRED,
            }
        ):
            raise RuntimeError(
                "position is not awaiting exit reconciliation"
            )

        if position.open_quantity <= 0:
            raise ValueError(
                "cannot restore position with zero open quantity"
            )

        if position.closed_quantity > 0:
            restored_state = (
                ManagedPositionState
                .PARTIALLY_EXITED
            )
        else:
            restored_state = (
                ManagedPositionState.OPEN
            )

        updated = replace(
            position,
            state=restored_state,
            updated_at=changed_at,
        )

        return self._registry.replace(
            updated
        )

    def close_without_additional_fill(
        self,
        *,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> ManagedPosition:
        """
        Controlled close helper for cases where external
        reconciliation has already accounted for all exit fills
        and the registry quantities already show zero open qty.

        This method deliberately refuses to invent quantities
        or realized P&L.
        """

        position = self._registry.require(
            position_id
        )

        if position.open_quantity != 0:
            raise ValueError(
                "cannot close position while open quantity remains"
            )

        updated = replace(
            position,
            state=ManagedPositionState.CLOSED,
            updated_at=changed_at,
        )

        return self._registry.replace(
            updated
        )