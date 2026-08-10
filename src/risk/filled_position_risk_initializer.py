"""
Phoenix M07 filled-position risk initializer.

Formal integration boundary from:

    M06 FilledPosition
        ->
    M07 ManagedPosition

Responsibilities:
    - Consume the authoritative M06 FilledPosition.
    - Calculate stop loss from actual broker entry fill.
    - Create initial M07 ManagedPosition state.
    - Register the position exactly once.
    - Preserve contract, quantity, level, and entry identity.

No broker calls or order execution belong here.
"""

from __future__ import annotations

from datetime import datetime

from src.execution.position_exit_types import (
    FilledPosition,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
)
from src.risk.stop_loss_policy import (
    StopLossPolicy,
)


class FilledPositionRiskInitializer:
    """
    Initializes one M06 FilledPosition into M07 risk management.
    """

    def __init__(
        self,
        *,
        registry: PositionRegistry,
        stop_loss_policy: StopLossPolicy,
    ) -> None:
        self._registry = registry
        self._stop_loss_policy = (
            stop_loss_policy
        )

    @property
    def registry(
        self,
    ) -> PositionRegistry:
        """
        Return the exact M07 registry owned by this initializer.
        """

        return self._registry

    @property
    def stop_loss_policy(
        self,
    ) -> StopLossPolicy:
        """
        Return the exact stop policy used when a fill becomes
        a managed position.

        T14 uses its configured risk_points for the conservative
        pre-entry exposure check.
        """

        return self._stop_loss_policy

    def initialize(
        self,
        *,
        position: FilledPosition,
        initialized_at: datetime,
        risk_id: PositionRiskId | None = None,
    ) -> ManagedPosition:
        """
        Create and register the initial ManagedPosition.

        Initial M07 state:

            open_quantity   = full M06 filled quantity
            closed_quantity = 0
            realized_pnl    = 0
            state           = OPEN

        Stop loss is derived from:

            position.entry_price

        which is the actual M06 broker average fill.
        """

        if (
            initialized_at
            < position.filled_at
        ):
            raise ValueError(
                "initialized_at cannot be before "
                "position filled_at"
            )

        resolved_risk_id = (
            risk_id
            or self._default_risk_id(
                position
            )
        )

        stop_loss = (
            self._stop_loss_policy.calculate(
                entry_price=(
                    position.entry_price
                )
            )
        )

        managed = ManagedPosition(
            risk_id=resolved_risk_id,
            position=position,
            open_quantity=position.quantity,
            closed_quantity=0,
            realized_pnl=0.0,
            state=ManagedPositionState.OPEN,
            stop_loss=stop_loss,
            target=None,
            created_at=initialized_at,
            updated_at=initialized_at,
        )

        return self._registry.register(
            managed
        )

    @staticmethod
    def _default_risk_id(
        position: FilledPosition,
    ) -> PositionRiskId:
        """
        Deterministic M07 risk identity derived from
        M06 FilledPositionId.
        """

        return PositionRiskId(
            value=(
                "RISK:"
                f"{position.position_id.value}"
            )
        )