"""
Phoenix M04 Re-entry adapter.

Bridges the generic M07 ReentrySyncPort to the existing
M04 ReentryStateManager.

Re-entry identity is:
    instrument_security_id + EntryLevel
"""

from __future__ import annotations

from datetime import datetime

from src.execution.position_exit_types import FilledPositionId
from src.signals.reentry_state_manager import ReentryStateManager
from src.strategy.strategy_types import EntryLevel


class M04ReentryAdapter:
    def __init__(
        self,
        *,
        manager: ReentryStateManager,
    ) -> None:
        self._manager = manager

    def mark_position_open(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> None:
        del position_id

        self._manager.mark_open(
            instrument_security_id=(
                instrument_security_id
            ),
            level=level,
            trading_date=changed_at.date(),
            opened_at=changed_at,
        )

    def mark_position_closed(
        self,
        *,
        instrument_security_id: str,
        level: EntryLevel,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> None:
        del position_id

        self._manager.mark_closed(
            instrument_security_id=(
                instrument_security_id
            ),
            level=level,
            closed_at=changed_at,
        )
