"""
Phoenix M13 operator read snapshot service.

This service adapts existing M08/M07 authoritative state into
transport-neutral immutable read models.

Ownership rules:

- Runtime state remains owned by TradingRuntimeOrchestrator.
- Position state remains owned by PositionRegistry.
- M13 never mutates either owner.
- Each source is read exactly once per capture so one response
  cannot mix multiple registry/runtime reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.api.api_types import (
    OperatorPositionSummary,
    OperatorRuntimeView,
    OperatorSnapshot,
)
from src.runtime.runtime_types import (
    RuntimeSnapshot,
)


class RuntimeSnapshotReader(
    Protocol,
):
    """
    Structural read-only M08 runtime boundary.
    """

    @property
    def snapshot(
        self,
    ) -> RuntimeSnapshot:
        ...


class ManagedPositionView(
    Protocol,
):
    """
    Minimum M07 position fields required by M13.
    """

    @property
    def open_quantity(
        self,
    ) -> int:
        ...

    @property
    def realized_pnl(
        self,
    ) -> float:
        ...


class PositionSnapshotReader(
    Protocol,
):
    """
    Structural read-only M07 registry boundary.
    """

    def all(
        self,
    ) -> tuple[
        ManagedPositionView,
        ...,
    ]:
        ...


class OperatorSnapshotService:
    """
    Build a passive operator snapshot from existing owners.

    No refresh, transition, persistence write, execution,
    notification, or event publication is performed here.
    """

    def __init__(
        self,
        *,
        runtime: RuntimeSnapshotReader,
        positions: PositionSnapshotReader,
    ) -> None:
        self._runtime = runtime
        self._positions = positions

    @property
    def runtime(
        self,
    ) -> RuntimeSnapshotReader:
        return self._runtime

    @property
    def positions(
        self,
    ) -> PositionSnapshotReader:
        return self._positions

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorSnapshot:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be datetime"
            )

        # Read each authoritative owner exactly once.
        runtime = self._runtime.snapshot
        positions = self._positions.all()

        runtime_view = OperatorRuntimeView(
            runtime_id=(
                runtime.runtime_id.value
            ),
            trading_date=(
                runtime.trading_date
            ),
            mode=str(
                runtime.mode.value
            ),
            state=str(
                runtime.state.value
            ),
            started_at=(
                runtime.started_at
            ),
            updated_at=(
                runtime.updated_at
            ),
            stopped_at=(
                runtime.stopped_at
            ),
            recovery_required=(
                runtime.recovery_required
            ),
            recovered=(
                runtime.recovered
            ),
            has_failure=(
                runtime.failure is not None
            ),
        )

        position_summary = (
            OperatorPositionSummary(
                tracked_position_count=len(
                    positions
                ),
                open_position_count=sum(
                    1
                    for position in positions
                    if position.open_quantity > 0
                ),
                open_quantity=sum(
                    position.open_quantity
                    for position in positions
                ),
                realized_pnl=float(
                    sum(
                        position.realized_pnl
                        for position in positions
                    )
                ),
            )
        )

        return OperatorSnapshot(
            runtime=runtime_view,
            positions=position_summary,
            captured_at=captured_at,
        )


__all__ = [
    "ManagedPositionView",
    "OperatorSnapshotService",
    "PositionSnapshotReader",
    "RuntimeSnapshotReader",
]
