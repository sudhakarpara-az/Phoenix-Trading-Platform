"""
Phoenix M07 re-entry risk synchronization.

Synchronizes actual M07 position lifecycle state with the
existing M04 re-entry subsystem.

Critical rule:

    re-entry cannot be released because an exit signal occurred
    or because a SELL order was submitted.

Re-entry may only be released after M07 proves that:

    open_quantity == 0
    and
    state == CLOSED

This module does not implement M04 re-entry policy itself.
It exposes a narrow port so the existing M04 ReentryStateManager
can be connected without changing its architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


class ReentrySyncPort(Protocol):
    """
    Narrow M07 -> M04 synchronization port.

    The concrete adapter for the existing M04
    ReentryStateManager will implement this interface.
    """

    def mark_position_open(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> None:
        ...

    def mark_position_closed(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> None:
        ...


class ReentrySyncStatus(str, Enum):
    OPEN_POSITION_SYNCED = (
        "OPEN_POSITION_SYNCED"
    )

    CLOSED_POSITION_SYNCED = (
        "CLOSED_POSITION_SYNCED"
    )

    STILL_OPEN = "STILL_OPEN"

    ALREADY_SYNCED = "ALREADY_SYNCED"


@dataclass(frozen=True, slots=True)
class ReentrySyncResult:
    position_id: FilledPositionId

    level: EntryLevel

    status: ReentrySyncStatus

    open_quantity: int

    synchronized_at: datetime

    @property
    def reentry_released(self) -> bool:
        return (
            self.status
            is ReentrySyncStatus
            .CLOSED_POSITION_SYNCED
        )


class ReentryRiskSynchronizer:
    """
    Synchronizes M07 position truth to the M04 re-entry layer.
    """

    def __init__(
        self,
        *,
        registry: PositionRegistry,
        reentry_port: ReentrySyncPort,
    ) -> None:
        self._registry = registry
        self._reentry_port = reentry_port

        self._open_synced: set[str] = set()
        self._closed_synced: set[str] = set()

    def sync_position_open(
        self,
        *,
        position_id: FilledPositionId,
        synchronized_at: datetime,
    ) -> ReentrySyncResult:
        """
        Inform M04 that a real managed position now exists.

        This should happen after M06 -> M07 initialization.
        """

        position = self._registry.require(
            position_id
        )

        if position.open_quantity <= 0:
            raise ValueError(
                "cannot synchronize open state for "
                "position with zero open quantity"
            )

        key = position.position_id.value

        if key in self._open_synced:
            return ReentrySyncResult(
                position_id=position.position_id,
                level=position.position.level,
                status=(
                    ReentrySyncStatus.ALREADY_SYNCED
                ),
                open_quantity=position.open_quantity,
                synchronized_at=synchronized_at,
            )

        self._reentry_port.mark_position_open(
            instrument_security_id=(
                position.security_id
            ),
            level=position.position.level,
            position_id=position.position_id,
            changed_at=synchronized_at,
        )

        self._open_synced.add(
            key
        )

        return ReentrySyncResult(
            position_id=position.position_id,
            level=position.position.level,
            status=(
                ReentrySyncStatus
                .OPEN_POSITION_SYNCED
            ),
            open_quantity=position.open_quantity,
            synchronized_at=synchronized_at,
        )

    def sync_position_state(
        self,
        *,
        position_id: FilledPositionId,
        synchronized_at: datetime,
    ) -> ReentrySyncResult:
        """
        Synchronize current M07 lifecycle state.

        Re-entry release occurs only when:
            state == CLOSED
            open_quantity == 0
        """

        position = self._registry.require(
            position_id
        )

        key = position.position_id.value

        if not self._is_genuinely_closed(
            position
        ):
            return ReentrySyncResult(
                position_id=position.position_id,
                level=position.position.level,
                status=ReentrySyncStatus.STILL_OPEN,
                open_quantity=position.open_quantity,
                synchronized_at=synchronized_at,
            )

        if key in self._closed_synced:
            return ReentrySyncResult(
                position_id=position.position_id,
                level=position.position.level,
                status=(
                    ReentrySyncStatus.ALREADY_SYNCED
                ),
                open_quantity=0,
                synchronized_at=synchronized_at,
            )

        self._reentry_port.mark_position_closed(
            instrument_security_id=(
                position.security_id
            ),
            level=position.position.level,
            position_id=position.position_id,
            changed_at=synchronized_at,
        )

        self._closed_synced.add(
            key
        )

        return ReentrySyncResult(
            position_id=position.position_id,
            level=position.position.level,
            status=(
                ReentrySyncStatus
                .CLOSED_POSITION_SYNCED
            ),
            open_quantity=0,
            synchronized_at=synchronized_at,
        )

    def is_closed_synced(
        self,
        position_id: FilledPositionId,
    ) -> bool:
        return (
            position_id.value
            in self._closed_synced
        )

    def clear(
        self,
    ) -> None:
        self._open_synced.clear()
        self._closed_synced.clear()

    @staticmethod
    def _is_genuinely_closed(
        position: ManagedPosition,
    ) -> bool:
        return (
            position.state
            is ManagedPositionState.CLOSED
            and position.open_quantity == 0
        )
