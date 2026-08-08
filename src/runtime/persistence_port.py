"""
Phoenix M08 persistence checkpoint boundary.

Defines the runtime-facing persistence contract without exposing
SQLAlchemy or database ORM models to the runtime package.
"""

from __future__ import annotations

from typing import Protocol

from src.runtime.runtime_events import RuntimeEvent
from src.runtime.runtime_types import RuntimeSnapshot


class PersistenceCheckpointPort(
    Protocol,
):
    """
    Persistence contract consumed by M08 runtime orchestration.

    Concrete implementation belongs to src.database.
    """

    def checkpoint_runtime(
        self,
        snapshot: RuntimeSnapshot,
    ) -> None:
        ...

    def checkpoint_event(
        self,
        event: RuntimeEvent,
    ) -> None:
        ...

    def runtime_exists(
        self,
        runtime_id: str,
    ) -> bool:
        ...