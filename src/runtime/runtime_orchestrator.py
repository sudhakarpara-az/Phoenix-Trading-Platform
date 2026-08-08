"""
Phoenix M08 Trading Runtime Orchestrator.

Coordinates application-level lifecycle for the Phoenix
Trading Platform.

Responsibilities:
    - own RuntimeSnapshot state
    - manage startup / ready / running / stopping / stopped
    - manage recovery-required startup path
    - publish lifecycle events
    - register runtime components
    - start/stop components in deterministic order
    - map runtime mode to application execution behavior
    - fail closed when a critical component fails

Important:

    This module does NOT contain:
        - KS strategy calculations
        - signal generation rules
        - option selection logic
        - order pricing logic
        - broker execution logic
        - position risk logic

Those remain in M02-M07.

M08-T06 establishes orchestration only.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    replace,
)
from datetime import (
    date,
    datetime,
)
from threading import RLock
from typing import (
    Protocol,
)

from src.runtime.event_bus import (
    RuntimeEventBus,
    RuntimeEventDispatchError,
)
from src.runtime.runtime_events import (
    RuntimeEvent,
    RuntimeEventType,
)
from src.runtime.runtime_types import (
    RuntimeFailure,
    RuntimeFailureCode,
    RuntimeId,
    RuntimeMode,
    RuntimeSnapshot,
    RuntimeState,
)


class RuntimeComponent(
    Protocol,
):
    """
    Minimal lifecycle contract for components managed by the
    orchestrator.

    M02-M07 adapters may implement this contract later without
    changing their existing business classes.
    """

    @property
    def name(
        self,
    ) -> str:
        ...

    def start(
        self,
    ) -> None:
        ...

    def stop(
        self,
    ) -> None:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class RegisteredRuntimeComponent:
    """
    Component registration metadata.
    """

    component: RuntimeComponent

    order: int

    critical: bool = True

    @property
    def name(
        self,
    ) -> str:
        return self.component.name


class DuplicateRuntimeComponentError(
    ValueError
):
    """
    Raised when the same runtime component name is registered
    more than once.
    """


class RuntimeTransitionError(
    RuntimeError
):
    """
    Raised when an illegal runtime lifecycle transition is
    attempted.
    """


class TradingRuntimeOrchestrator:
    """
    Application-level Phoenix lifecycle coordinator.

    Startup order:
        lowest component order first

    Shutdown order:
        reverse startup order

    This guarantees dependencies are stopped after their
    consumers whenever possible.
    """

    def __init__(
        self,
        *,
        runtime_id: RuntimeId,
        trading_date: date,
        mode: RuntimeMode,
        event_bus: RuntimeEventBus,
        created_at: datetime,
        recovery_required: bool = False,
    ) -> None:
        self._event_bus = event_bus

        self._components: dict[
            str,
            RegisteredRuntimeComponent,
        ] = {}

        self._lock = RLock()

        self._snapshot = RuntimeSnapshot(
            runtime_id=runtime_id,
            trading_date=trading_date,
            mode=mode,
            state=RuntimeState.CREATED,
            started_at=None,
            updated_at=created_at,
            stopped_at=None,
            failure=None,
            recovery_required=(
                recovery_required
            ),
            recovered=False,
        )

    # ========================================================
    # Public state
    # ========================================================

    @property
    def snapshot(
        self,
    ) -> RuntimeSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def state(
        self,
    ) -> RuntimeState:
        return self.snapshot.state

    @property
    def mode(
        self,
    ) -> RuntimeMode:
        return self.snapshot.mode

    @property
    def runtime_id(
        self,
    ) -> RuntimeId:
        return self.snapshot.runtime_id

    @property
    def recovery_required(
        self,
    ) -> bool:
        return (
            self.snapshot
            .recovery_required
        )

    # ========================================================
    # Component registration
    # ========================================================

    def register_component(
        self,
        *,
        component: RuntimeComponent,
        order: int,
        critical: bool = True,
    ) -> None:
        """
        Register one managed runtime component.

        Registration is allowed only before startup.
        """

        name = component.name.strip()

        if not name:
            raise ValueError(
                "runtime component name cannot be empty"
            )

        if order < 0:
            raise ValueError(
                "runtime component order cannot be negative"
            )

        with self._lock:
            if (
                self._snapshot.state
                is not RuntimeState.CREATED
            ):
                raise RuntimeTransitionError(
                    "runtime components can only be "
                    "registered while runtime is CREATED"
                )

            if name in self._components:
                raise (
                    DuplicateRuntimeComponentError(
                        "runtime component already "
                        f"registered: {name}"
                    )
                )

            self._components[
                name
            ] = RegisteredRuntimeComponent(
                component=component,
                order=order,
                critical=critical,
            )

    def registered_components(
        self,
    ) -> tuple[
        RegisteredRuntimeComponent,
        ...
    ]:
        with self._lock:
            return tuple(
                sorted(
                    self._components.values(),
                    key=lambda item: (
                        item.order,
                        item.name,
                    ),
                )
            )

    # ========================================================
    # Startup
    # ========================================================

    def start(
        self,
        *,
        started_at: datetime,
    ) -> RuntimeSnapshot:
        """
        Start Phoenix runtime components.

        CREATED
          ->
        STARTING
          ->
        RECOVERING   if required

        or

        READY        for clean startup
        """

        with self._lock:
            if (
                self._snapshot.state
                is not RuntimeState.CREATED
            ):
                raise RuntimeTransitionError(
                    "runtime can only start from CREATED"
                )

            self._snapshot = replace(
                self._snapshot,
                state=RuntimeState.STARTING,
                started_at=started_at,
                updated_at=started_at,
            )

        self._publish_lifecycle_event(
            event_type=(
                RuntimeEventType
                .RUNTIME_STARTED
            ),
            occurred_at=started_at,
        )

        started_components: list[
            RegisteredRuntimeComponent
        ] = []

        try:
            for registration in (
                self.registered_components()
            ):
                registration.component.start()

                started_components.append(
                    registration
                )

        except Exception as exc:
            self._rollback_started_components(
                started_components
            )

            return self.fail(
                code=(
                    RuntimeFailureCode
                    .STARTUP_FAILED
                ),
                message=(
                    "runtime component startup failed: "
                    f"{exc}"
                ),
                failed_at=started_at,
                component=(
                    registration.name
                    if "registration" in locals()
                    else None
                ),
                recoverable=False,
            )

        with self._lock:
            if self._snapshot.recovery_required:
                self._snapshot = replace(
                    self._snapshot,
                    state=RuntimeState.RECOVERING,
                    updated_at=started_at,
                )

                event_type = (
                    RuntimeEventType
                    .RECOVERY_STARTED
                )

            else:
                self._snapshot = replace(
                    self._snapshot,
                    state=RuntimeState.READY,
                    updated_at=started_at,
                )

                event_type = (
                    RuntimeEventType
                    .RUNTIME_READY
                )

        self._publish_lifecycle_event(
            event_type=event_type,
            occurred_at=started_at,
        )

        return self.snapshot

    # ========================================================
    # Recovery lifecycle
    # ========================================================

    def complete_recovery(
        self,
        *,
        completed_at: datetime,
    ) -> RuntimeSnapshot:
        """
        RECOVERING -> READY
        """

        with self._lock:
            if (
                self._snapshot.state
                is not RuntimeState.RECOVERING
            ):
                raise RuntimeTransitionError(
                    "recovery can only complete from "
                    "RECOVERING state"
                )

            self._snapshot = replace(
                self._snapshot,
                state=RuntimeState.READY,
                recovery_required=False,
                recovered=True,
                updated_at=completed_at,
            )

        self._publish_lifecycle_event(
            event_type=(
                RuntimeEventType
                .RECOVERY_COMPLETED
            ),
            occurred_at=completed_at,
        )

        self._publish_lifecycle_event(
            event_type=(
                RuntimeEventType
                .RUNTIME_READY
            ),
            occurred_at=completed_at,
        )

        return self.snapshot

    # ========================================================
    # Running
    # ========================================================

    def run(
        self,
        *,
        running_at: datetime,
    ) -> RuntimeSnapshot:
        """
        READY -> RUNNING
        """

        with self._lock:
            if (
                self._snapshot.state
                is not RuntimeState.READY
            ):
                raise RuntimeTransitionError(
                    "runtime can only run from READY"
                )

            self._snapshot = replace(
                self._snapshot,
                state=RuntimeState.RUNNING,
                updated_at=running_at,
            )

        return self.snapshot

    # ========================================================
    # Shutdown
    # ========================================================

    def stop(
        self,
        *,
        stopped_at: datetime,
    ) -> RuntimeSnapshot:
        """
        Gracefully stop runtime.

        READY / RUNNING / RECOVERING
              ->
        STOPPING
              ->
        STOPPED

        Components stop in reverse startup order.
        """

        with self._lock:
            if self._snapshot.state not in {
                RuntimeState.READY,
                RuntimeState.RUNNING,
                RuntimeState.RECOVERING,
            }:
                raise RuntimeTransitionError(
                    "runtime cannot stop from "
                    f"{self._snapshot.state.value}"
                )

            self._snapshot = replace(
                self._snapshot,
                state=RuntimeState.STOPPING,
                updated_at=stopped_at,
            )

        self._publish_lifecycle_event(
            event_type=(
                RuntimeEventType
                .RUNTIME_STOPPING
            ),
            occurred_at=stopped_at,
        )

        failures: list[
            tuple[str, Exception]
        ] = []

        for registration in reversed(
            self.registered_components()
        ):
            try:
                registration.component.stop()

            except Exception as exc:
                failures.append(
                    (
                        registration.name,
                        exc,
                    )
                )

                if registration.critical:
                    break

        if failures:
            name, exc = failures[0]

            return self.fail(
                code=(
                    RuntimeFailureCode
                    .SHUTDOWN_FAILED
                ),
                message=(
                    "runtime component shutdown failed: "
                    f"{exc}"
                ),
                failed_at=stopped_at,
                component=name,
                recoverable=False,
            )

        with self._lock:
            self._snapshot = replace(
                self._snapshot,
                state=RuntimeState.STOPPED,
                stopped_at=stopped_at,
                updated_at=stopped_at,
            )

        self._publish_lifecycle_event(
            event_type=(
                RuntimeEventType
                .RUNTIME_STOPPED
            ),
            occurred_at=stopped_at,
        )

        return self.snapshot

    # ========================================================
    # Failure
    # ========================================================

    def fail(
        self,
        *,
        code: RuntimeFailureCode,
        message: str,
        failed_at: datetime,
        component: str | None = None,
        recoverable: bool = False,
    ) -> RuntimeSnapshot:
        """
        Transition the current runtime to FAILED.

        FAILED blocks all runtime-level entry processing.
        """

        failure = RuntimeFailure(
            code=code,
            message=message,
            occurred_at=failed_at,
            recoverable=recoverable,
            component=component,
        )

        with self._lock:
            if (
                self._snapshot.state
                is RuntimeState.STOPPED
            ):
                raise RuntimeTransitionError(
                    "STOPPED runtime cannot transition "
                    "to FAILED"
                )

            self._snapshot = replace(
                self._snapshot,
                state=RuntimeState.FAILED,
                updated_at=failed_at,
                stopped_at=None,
                failure=failure,
                recovery_required=(
                    self._snapshot.recovery_required
                    or recoverable
                ),
            )

        try:
            self._publish_lifecycle_event(
                event_type=(
                    RuntimeEventType
                    .RUNTIME_FAILED
                ),
                occurred_at=failed_at,
                payload=failure,
            )

        except RuntimeEventDispatchError:
            # Runtime is already FAILED.
            # Failure publication must not hide the original
            # failure state.
            pass

        return self.snapshot

    # ========================================================
    # Runtime gates
    # ========================================================

    def can_process_market_data(
        self,
    ) -> bool:
        return (
            self.snapshot
            .can_process_market_data
        )

    def can_accept_new_entries(
        self,
    ) -> bool:
        return (
            self.snapshot
            .can_accept_new_entries
        )

    def live_execution_allowed(
        self,
    ) -> bool:
        """
        Runtime-level LIVE gate.

        M06 still performs its own execution eligibility and
        safety validation.
        """

        snapshot = self.snapshot

        return (
            snapshot.mode
            is RuntimeMode.LIVE
            and snapshot.state
            is RuntimeState.RUNNING
            and not snapshot.recovery_required
            and snapshot.failure is None
        )

    # ========================================================
    # Helpers
    # ========================================================

    def _publish_lifecycle_event(
        self,
        *,
        event_type: RuntimeEventType,
        occurred_at: datetime,
        payload=None,
    ) -> None:
        event = RuntimeEvent.create(
            runtime_id=(
                self._snapshot.runtime_id
            ),
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            correlation_id=(
                self._snapshot.runtime_id.value
            ),
        )

        self._event_bus.publish(
            event
        )

    @staticmethod
    def _rollback_started_components(
        started_components: list[
            RegisteredRuntimeComponent
        ],
    ) -> None:
        """
        Best-effort rollback when startup fails.

        Components already started are stopped in reverse order.

        Rollback failures are intentionally ignored here because
        the primary startup failure must remain authoritative.
        Later health/recovery work will make these observable.
        """

        for registration in reversed(
            started_components
        ):
            try:
                registration.component.stop()
            except Exception:
                pass