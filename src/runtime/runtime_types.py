"""
Phoenix M08 runtime domain models.

Defines application-level runtime identity, mode, lifecycle
state, failure information, and immutable runtime snapshots.

This module contains no:
    - database access
    - broker access
    - market-data access
    - orchestration logic
    - persistence implementation

Those responsibilities are introduced by later M08 tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeId:
    """
    Stable identity for one Phoenix runtime session.

    Example:
        PHOENIX:2026-08-08:LIVE
    """

    value: str

    def __post_init__(
        self,
    ) -> None:
        normalized = self.value.strip()

        if not normalized:
            raise ValueError(
                "runtime id cannot be empty"
            )

        if normalized != self.value:
            object.__setattr__(
                self,
                "value",
                normalized,
            )

    def __str__(
        self,
    ) -> str:
        return self.value


class RuntimeMode(
    str,
    Enum,
):
    """
    Phoenix application execution mode.

    DRY_RUN:
        Runtime processes strategy/signals/orders but must not
        create real broker-side executions.

    LIVE:
        Runtime is permitted to use the configured live
        execution path, subject to M06 safety gates.
    """

    DRY_RUN = "DRY_RUN"

    LIVE = "LIVE"


class RuntimeState(
    str,
    Enum,
):
    """
    Application lifecycle state.
    """

    CREATED = "CREATED"

    STARTING = "STARTING"

    RECOVERING = "RECOVERING"

    READY = "READY"

    RUNNING = "RUNNING"

    STOPPING = "STOPPING"

    STOPPED = "STOPPED"

    FAILED = "FAILED"


class RuntimeFailureCode(
    str,
    Enum,
):
    """
    High-level runtime failure categories.

    These categories intentionally describe runtime concerns
    rather than broker-specific implementation errors.
    """

    STARTUP_FAILED = "STARTUP_FAILED"

    RECOVERY_FAILED = "RECOVERY_FAILED"

    DATABASE_FAILED = "DATABASE_FAILED"

    MARKET_DATA_FAILED = "MARKET_DATA_FAILED"

    EXECUTION_FAILED = "EXECUTION_FAILED"

    RISK_FAILED = "RISK_FAILED"

    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"

    SHUTDOWN_FAILED = "SHUTDOWN_FAILED"

    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeFailure:
    """
    Immutable description of the latest fatal runtime failure.

    `recoverable` expresses whether an orchestrator may attempt
    a controlled recovery path.

    It does not mean Phoenix should automatically retry.
    """

    code: RuntimeFailureCode

    message: str

    occurred_at: datetime

    recoverable: bool = False

    component: str | None = None

    def __post_init__(
        self,
    ) -> None:
        message = self.message.strip()

        if not message:
            raise ValueError(
                "runtime failure message "
                "cannot be empty"
            )

        if message != self.message:
            object.__setattr__(
                self,
                "message",
                message,
            )

        if self.component is not None:
            component = (
                self.component.strip()
            )

            if not component:
                raise ValueError(
                    "runtime failure component "
                    "cannot be empty"
                )

            if (
                component
                != self.component
            ):
                object.__setattr__(
                    self,
                    "component",
                    component,
                )


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeSnapshot:
    """
    Immutable point-in-time Phoenix runtime state.

    This becomes the persistence/recovery boundary in later M08
    tasks.

    Important:
        A snapshot describes runtime state.

        It does NOT contain broker credentials, tokens, or other
        secrets.
    """

    runtime_id: RuntimeId

    trading_date: date

    mode: RuntimeMode

    state: RuntimeState

    started_at: datetime | None

    updated_at: datetime

    stopped_at: datetime | None = None

    failure: RuntimeFailure | None = None

    recovery_required: bool = False

    recovered: bool = False

    def __post_init__(
        self,
    ) -> None:
        # --------------------------------------------------
        # Basic lifecycle timestamps
        # --------------------------------------------------

        if (
            self.started_at is not None
            and self.updated_at
            < self.started_at
        ):
            raise ValueError(
                "runtime updated_at cannot be "
                "before started_at"
            )

        if self.stopped_at is not None:
            if self.started_at is None:
                raise ValueError(
                    "stopped runtime requires "
                    "started_at"
                )

            if (
                self.stopped_at
                < self.started_at
            ):
                raise ValueError(
                    "runtime stopped_at cannot be "
                    "before started_at"
                )

            if (
                self.updated_at
                < self.stopped_at
            ):
                raise ValueError(
                    "runtime updated_at cannot be "
                    "before stopped_at"
                )

        # --------------------------------------------------
        # CREATED
        # --------------------------------------------------

        if (
            self.state
            is RuntimeState.CREATED
        ):
            if self.started_at is not None:
                raise ValueError(
                    "CREATED runtime cannot have "
                    "started_at"
                )

            if self.stopped_at is not None:
                raise ValueError(
                    "CREATED runtime cannot have "
                    "stopped_at"
                )

            if self.failure is not None:
                raise ValueError(
                    "CREATED runtime cannot have "
                    "failure"
                )

        # --------------------------------------------------
        # Active lifecycle states require startup timestamp.
        # --------------------------------------------------

        if self.state in {
            RuntimeState.STARTING,
            RuntimeState.RECOVERING,
            RuntimeState.READY,
            RuntimeState.RUNNING,
            RuntimeState.STOPPING,
            RuntimeState.STOPPED,
        }:
            if self.started_at is None:
                raise ValueError(
                    f"{self.state.value} runtime "
                    "requires started_at"
                )

        # --------------------------------------------------
        # STOPPED
        # --------------------------------------------------

        if (
            self.state
            is RuntimeState.STOPPED
            and self.stopped_at is None
        ):
            raise ValueError(
                "STOPPED runtime requires "
                "stopped_at"
            )

        if (
            self.state
            is not RuntimeState.STOPPED
            and self.stopped_at is not None
        ):
            raise ValueError(
                "only STOPPED runtime may have "
                "stopped_at"
            )

        # --------------------------------------------------
        # FAILED
        # --------------------------------------------------

        if (
            self.state
            is RuntimeState.FAILED
            and self.failure is None
        ):
            raise ValueError(
                "FAILED runtime requires failure"
            )

        if (
            self.state
            is not RuntimeState.FAILED
            and self.failure is not None
        ):
            raise ValueError(
                "runtime failure is only valid "
                "for FAILED state"
            )

        if (
            self.failure is not None
            and self.failure.occurred_at
            > self.updated_at
        ):
            raise ValueError(
                "runtime failure cannot occur "
                "after snapshot updated_at"
            )

        # --------------------------------------------------
        # Recovery invariants
        # --------------------------------------------------

        if (
            self.state
            is RuntimeState.RECOVERING
            and not self.recovery_required
        ):
            raise ValueError(
                "RECOVERING runtime must have "
                "recovery_required=True"
            )

        if (
            self.recovered
            and self.recovery_required
        ):
            raise ValueError(
                "recovered runtime cannot still "
                "require recovery"
            )

        if (
            self.state
            is RuntimeState.CREATED
            and self.recovered
        ):
            raise ValueError(
                "CREATED runtime cannot be "
                "marked recovered"
            )

    @property
    def is_terminal(
        self,
    ) -> bool:
        return self.state in {
            RuntimeState.STOPPED,
            RuntimeState.FAILED,
        }

    @property
    def is_active(
        self,
    ) -> bool:
        return self.state in {
            RuntimeState.STARTING,
            RuntimeState.RECOVERING,
            RuntimeState.READY,
            RuntimeState.RUNNING,
            RuntimeState.STOPPING,
        }

    @property
    def can_process_market_data(
        self,
    ) -> bool:
        """
        Only a fully running runtime may process the live
        trading pipeline.
        """

        return (
            self.state
            is RuntimeState.RUNNING
        )

    @property
    def can_accept_new_entries(
        self,
    ) -> bool:
        """
        Runtime-level gate only.

        M04, M07 exposure, daily-risk and session-window gates
        are evaluated separately.
        """

        return (
            self.state
            is RuntimeState.RUNNING
            and not self.recovery_required
            and self.failure is None
        )