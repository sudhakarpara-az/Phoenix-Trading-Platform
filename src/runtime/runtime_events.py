"""
Phoenix M08 runtime event domain models.

Defines typed internal runtime events used to communicate
between Phoenix runtime components.

This module contains no:
    - broker calls
    - database calls
    - market-data implementation
    - strategy execution
    - threading
    - asynchronous dispatch

M08-T05 intentionally keeps event delivery synchronous and
deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from src.runtime.runtime_types import (
    RuntimeId,
)


class RuntimeEventType(
    str,
    Enum,
):
    """
    Application-level Phoenix event categories.

    These event types describe runtime/business transitions,
    not broker-specific callback names.
    """

    RUNTIME_STARTED = "RUNTIME_STARTED"
    RUNTIME_READY = "RUNTIME_READY"
    RUNTIME_STOPPING = "RUNTIME_STOPPING"
    RUNTIME_STOPPED = "RUNTIME_STOPPED"
    RUNTIME_FAILED = "RUNTIME_FAILED"

    MARKET_TICK = "MARKET_TICK"

    SIGNAL_CREATED = "SIGNAL_CREATED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"

    OPTION_SELECTED = "OPTION_SELECTED"
    OPTION_SELECTION_FAILED = (
        "OPTION_SELECTION_FAILED"
    )

    ENTRY_ORDER_CREATED = "ENTRY_ORDER_CREATED"
    ENTRY_ORDER_SUBMITTED = (
        "ENTRY_ORDER_SUBMITTED"
    )
    ENTRY_ORDER_FILLED = "ENTRY_ORDER_FILLED"
    ENTRY_ORDER_FAILED = "ENTRY_ORDER_FAILED"

    POSITION_OPENED = "POSITION_OPENED"
    POSITION_UPDATED = "POSITION_UPDATED"

    TARGET_TRIGGERED = "TARGET_TRIGGERED"
    STOP_LOSS_TRIGGERED = (
        "STOP_LOSS_TRIGGERED"
    )
    FORCE_EXIT_TRIGGERED = (
        "FORCE_EXIT_TRIGGERED"
    )

    EXIT_ORDER_CREATED = "EXIT_ORDER_CREATED"
    EXIT_ORDER_SUBMITTED = (
        "EXIT_ORDER_SUBMITTED"
    )
    EXIT_ORDER_FILLED = "EXIT_ORDER_FILLED"
    EXIT_ORDER_FAILED = "EXIT_ORDER_FAILED"

    POSITION_CLOSED = "POSITION_CLOSED"

    PNL_UPDATED = "PNL_UPDATED"
    RISK_UPDATED = "RISK_UPDATED"

    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_COMPLETED = "RECOVERY_COMPLETED"
    RECOVERY_FAILED = "RECOVERY_FAILED"

    HEALTH_CHANGED = "HEALTH_CHANGED"


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeEvent:
    """
    Immutable event transported through RuntimeEventBus.

    payload:
        Application data associated with the event.

        The bus treats payload as opaque. Individual consumers
        are responsible for interpreting the expected payload
        type for the event they subscribe to.

    correlation_id:
        Used to associate multiple runtime events belonging to
        one logical workflow.

        Example:
            SIGNAL_CREATED
                ->
            OPTION_SELECTED
                ->
            ENTRY_ORDER_SUBMITTED
                ->
            POSITION_OPENED

        may all share the same correlation id.

    causation_id:
        Identifies the event that caused this event.
    """

    event_id: str

    runtime_id: RuntimeId

    event_type: RuntimeEventType

    occurred_at: datetime

    payload: Any = None

    correlation_id: str | None = None

    causation_id: str | None = None

    def __post_init__(
        self,
    ) -> None:
        event_id = self.event_id.strip()

        if not event_id:
            raise ValueError(
                "runtime event id cannot be empty"
            )

        if event_id != self.event_id:
            object.__setattr__(
                self,
                "event_id",
                event_id,
            )

        if self.correlation_id is not None:
            correlation_id = (
                self.correlation_id.strip()
            )

            if not correlation_id:
                raise ValueError(
                    "runtime event correlation id "
                    "cannot be empty"
                )

            if (
                correlation_id
                != self.correlation_id
            ):
                object.__setattr__(
                    self,
                    "correlation_id",
                    correlation_id,
                )

        if self.causation_id is not None:
            causation_id = (
                self.causation_id.strip()
            )

            if not causation_id:
                raise ValueError(
                    "runtime event causation id "
                    "cannot be empty"
                )

            if (
                causation_id
                != self.causation_id
            ):
                object.__setattr__(
                    self,
                    "causation_id",
                    causation_id,
                )

    @classmethod
    def create(
        cls,
        *,
        runtime_id: RuntimeId,
        event_type: RuntimeEventType,
        occurred_at: datetime,
        payload: Any = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> "RuntimeEvent":
        """
        Convenience factory using a unique internal event id.
        """

        return cls(
            event_id=str(
                uuid4()
            ),
            runtime_id=runtime_id,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )