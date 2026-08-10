"""
Phoenix Trading Platform

Deterministic Application Shutdown
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.app.container import (
    PhoenixPersistenceContainer,
    PhoenixRuntimeStartupContainer,
)
from src.core.logger import logger
from src.runtime.runtime_types import (
    RuntimeState,
)


class ApplicationShutdownError(
    RuntimeError
):
    """
    Phoenix application teardown could not be completed safely.
    """


@dataclass(
    frozen=True,
    slots=True,
)
class ApplicationShutdownResult:
    """
    Deterministic application teardown result.
    """

    runtime_state_before: RuntimeState
    runtime_state_after: RuntimeState

    runtime_stop_attempted: bool

    sessions_stopped: bool
    database_disposed: bool

    completed: bool

    message: str


class ShutdownManager:
    """
    Deterministic Phoenix teardown owner.

    Normal runtime component teardown remains owned by
    TradingRuntimeOrchestrator.stop().

    Persistence is always shut down afterward:

        DatabaseSessionManager.stop()
            ->
        DatabaseEngine.dispose()

    CREATED, FAILED and already STOPPED runtimes do not call
    TradingRuntimeOrchestrator.stop(), because its existing
    lifecycle contract does not permit those source states.

    STARTING and STOPPING are transitional states. Teardown
    refuses to dispose persistence underneath a runtime that
    is actively transitioning.
    """

    _NORMAL_STOP_STATES = frozenset(
        {
            RuntimeState.READY,
            RuntimeState.RUNNING,
            RuntimeState.RECOVERING,
        }
    )

    _SAFE_SKIP_STATES = frozenset(
        {
            RuntimeState.CREATED,
            RuntimeState.FAILED,
            RuntimeState.STOPPED,
        }
    )

    def __init__(
        self,
        *,
        runtime_startup:
            PhoenixRuntimeStartupContainer,
        persistence:
            PhoenixPersistenceContainer,
    ) -> None:
        if (
            runtime_startup.persistence
            is not persistence
        ):
            raise ValueError(
                "shutdown must use the exact persistence "
                "owned by runtime startup"
            )

        self._runtime_startup = (
            runtime_startup
        )

        self._persistence = (
            persistence
        )

    @property
    def runtime_startup(
        self,
    ) -> PhoenixRuntimeStartupContainer:
        return self._runtime_startup

    @property
    def persistence(
        self,
    ) -> PhoenixPersistenceContainer:
        return self._persistence

    def shutdown(
        self,
        *,
        stopped_at: datetime,
    ) -> ApplicationShutdownResult:
        """
        Gracefully tear down Phoenix application resources.

        Idempotent for already-stopped runtime/persistence.
        """

        if type(stopped_at) is not datetime:
            raise TypeError(
                "stopped_at must be a datetime"
            )

        orchestrator = (
            self._runtime_startup
            .orchestrator
        )

        state_before = (
            orchestrator.state
        )

        if state_before in {
            RuntimeState.STARTING,
            RuntimeState.STOPPING,
        }:
            raise ApplicationShutdownError(
                "cannot dispose application resources "
                "while runtime is in transitional state "
                f"{state_before.value}"
            )

        runtime_stop_attempted = False
        runtime_error: Exception | None = None

        if (
            state_before
            in self._NORMAL_STOP_STATES
        ):
            runtime_stop_attempted = True

            try:
                orchestrator.stop(
                    stopped_at=stopped_at
                )

            except Exception as exc:
                runtime_error = exc

        elif (
            state_before
            not in self._SAFE_SKIP_STATES
        ):
            raise ApplicationShutdownError(
                "unsupported runtime state during "
                f"shutdown: {state_before.value}"
            )

        # ----------------------------------------------------
        # Persistence teardown is independent and ordered.
        #
        # Even if normal runtime stop reports an exception,
        # Phoenix still attempts to close database resources.
        # ----------------------------------------------------

        persistence_errors: list[
            Exception
        ] = []

        try:
            if self._persistence.sessions.started:
                self._persistence.sessions.stop()

        except Exception as exc:
            persistence_errors.append(
                exc
            )

        try:
            if self._persistence.database.started:
                self._persistence.database.dispose()

        except Exception as exc:
            persistence_errors.append(
                exc
            )

        sessions_stopped = (
            not self._persistence
            .sessions
            .started
        )

        database_disposed = (
            not self._persistence
            .database
            .started
        )

        state_after = (
            orchestrator.state
        )

        if runtime_error is not None:
            raise ApplicationShutdownError(
                "runtime shutdown raised an exception; "
                "persistence teardown was still attempted: "
                f"{runtime_error}"
            ) from runtime_error

        if persistence_errors:
            first_error = (
                persistence_errors[0]
            )

            raise ApplicationShutdownError(
                "persistence shutdown failed: "
                f"{first_error}"
            ) from first_error

        normal_runtime_completed = (
            not runtime_stop_attempted
            or state_after
            is RuntimeState.STOPPED
        )

        completed = (
            normal_runtime_completed
            and sessions_stopped
            and database_disposed
        )

        if (
            runtime_stop_attempted
            and state_after
            is RuntimeState.FAILED
        ):
            message = (
                "runtime component shutdown failed closed; "
                "persistence resources were disposed"
            )

        elif (
            state_before
            is RuntimeState.FAILED
        ):
            message = (
                "FAILED runtime state preserved; "
                "persistence resources were disposed"
            )

        elif (
            state_before
            is RuntimeState.CREATED
        ):
            message = (
                "runtime was never started; "
                "persistence resources were disposed"
            )

        elif (
            state_before
            is RuntimeState.STOPPED
        ):
            message = (
                "runtime was already stopped; "
                "persistence teardown is idempotent"
            )

        else:
            message = (
                "Phoenix application shutdown completed"
            )

        if completed:
            logger.success(
                message
            )

        else:
            logger.error(
                message
            )

        return ApplicationShutdownResult(
            runtime_state_before=(
                state_before
            ),
            runtime_state_after=(
                state_after
            ),
            runtime_stop_attempted=(
                runtime_stop_attempted
            ),
            sessions_stopped=(
                sessions_stopped
            ),
            database_disposed=(
                database_disposed
            ),
            completed=completed,
            message=message,
        )


__all__ = [
    "ApplicationShutdownError",
    "ApplicationShutdownResult",
    "ShutdownManager",
]
