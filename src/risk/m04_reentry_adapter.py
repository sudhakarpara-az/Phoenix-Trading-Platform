"""
Adapter from M07's generic ReentrySyncPort to the existing
M04 ReentryStateManager API.
"""

from __future__ import annotations

from datetime import datetime

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)

# Import the EXISTING M04 manager here.
# Do not rename that class.


class M04ReentryAdapter:
    def __init__(
        self,
        *,
        manager,
    ) -> None:
        self._manager = manager

    def mark_position_open(
        self,
        *,
        level: EntryLevel,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> None:
        # Translate to the EXISTING M04 method.
        raise NotImplementedError

    def mark_position_closed(
        self,
        *,
        level: EntryLevel,
        position_id: FilledPositionId,
        changed_at: datetime,
    ) -> None:
        # Translate to the EXISTING M04 method.
        raise NotImplementedError