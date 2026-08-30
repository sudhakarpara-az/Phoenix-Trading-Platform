"""
M10 final application startup/shutdown lifecycle tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import (
    Any,
    cast,
)

import pytest

from src.app.recovery import (
    RecoveryStateRestorerBinding,
)
from src.app.shutdown import (
    ApplicationShutdownError,
    ShutdownManager,
)
from src.app.startup import (
    ApplicationStartupError,
    StartupManager,
)
from src.runtime.runtime_types import (
    RuntimeState,
)


NOW = datetime(
    2026,
    8,
    10,
    9,
    15,
)


@dataclass
class Snapshot:
    state: RuntimeState


class FakeStartupCoordinator:
    def __init__(
        self,
        *,
        result_state:
            RuntimeState = RuntimeState.RUNNING,
    ) -> None:
        self.calls: list[
            dict[str, Any]
        ] = []

        self.result_state = (
            result_state
        )

    def start(
        self,
        **kwargs: Any,
    ) -> Any:
        self.calls.append(
            kwargs
        )

        return SimpleNamespace(
            runtime=Snapshot(
                self.result_state
            )
        )


class FakeRecoveryService:
    def __init__(
        self,
        state_restorer: Any,
    ) -> None:
        self.state_restorer = (
            state_restorer
        )


class FakeOrchestrator:
    def __init__(
        self,
        *,
        state: RuntimeState,
        calls: list[str],
    ) -> None:
        self.state = state
        self.calls = calls
        self.stop_calls = 0

    def stop(
        self,
        *,
        stopped_at: datetime,
    ) -> Snapshot:
        del stopped_at

        self.calls.append(
            "orchestrator.stop"
        )

        self.stop_calls += 1
        self.state = (
            RuntimeState.STOPPED
        )

        return Snapshot(
            RuntimeState.STOPPED
        )


class FakeSessions:
    def __init__(
        self,
        calls: list[str],
        *,
        started: bool = True,
    ) -> None:
        self.calls = calls
        self.started = started

    def stop(
        self,
    ) -> None:
        self.calls.append(
            "sessions.stop"
        )

        self.started = False


class FakeDatabase:
    def __init__(
        self,
        calls: list[str],
        *,
        started: bool = True,
    ) -> None:
        self.calls = calls
        self.started = started

    def dispose(
        self,
    ) -> None:
        self.calls.append(
            "database.dispose"
        )

        self.started = False


def make_runtime_startup(
    *,
    recovery_required: bool,
    state_restorer: Any,
    coordinator:
        FakeStartupCoordinator,
    orchestrator: Any,
    persistence: Any = None,
    health_supervisor: Any = None,
) -> Any:
    return cast(
        Any,
        SimpleNamespace(
            persistence=persistence,
            recovery_plan=(
                SimpleNamespace(
                    recovery_required=(
                        recovery_required
                    )
                )
            ),
            recovery_service=(
                FakeRecoveryService(
                    state_restorer
                )
            ),
            startup_coordinator=(
                coordinator
            ),
            orchestrator=(
                orchestrator
            ),
            health_supervisor=(
                health_supervisor
            ),
        ),
    )


def test_runtime_start_delegates_to_exact_startup_coordinator():
    coordinator = (
        FakeStartupCoordinator()
    )

    orchestrator = object()

    runtime_startup = (
        make_runtime_startup(
            recovery_required=False,
            state_restorer=object(),
            coordinator=coordinator,
            orchestrator=orchestrator,
        )
    )

    manager = StartupManager()

    result = manager.start_runtime(
        runtime_startup=(
            runtime_startup
        ),
        started_at=NOW,
        recovery_checked_at=NOW,
        running_at=NOW,
    )

    assert (
        result.runtime.state
        is RuntimeState.RUNNING
    )

    assert len(
        coordinator.calls
    ) == 1

    call = coordinator.calls[0]

    assert (
        call["orchestrator"]
        is orchestrator
    )

    assert (
        call["recovery_plan"]
        is runtime_startup
        .recovery_plan
    )

    assert (
        call["started_at"]
        == NOW
    )

    assert (
        call["recovery_checked_at"]
        == NOW
    )

    assert (
        call["running_at"]
        == NOW
    )



def test_runtime_start_passes_exact_retained_health_supervisor() -> None:
    coordinator = (
        FakeStartupCoordinator()
    )

    orchestrator = object()
    health_supervisor = object()

    runtime_startup = (
        make_runtime_startup(
            recovery_required=False,
            state_restorer=object(),
            coordinator=coordinator,
            orchestrator=orchestrator,
            health_supervisor=health_supervisor,
        )
    )

    StartupManager().start_runtime(
        runtime_startup=runtime_startup,
        started_at=NOW,
    )

    assert (
        coordinator.calls[0][
            "health_supervisor"
        ]
        is health_supervisor
    )

def test_recovery_required_runtime_blocks_unbound_restorer():
    binding = (
        RecoveryStateRestorerBinding()
    )

    coordinator = (
        FakeStartupCoordinator()
    )

    runtime_startup = (
        make_runtime_startup(
            recovery_required=True,
            state_restorer=binding,
            coordinator=coordinator,
            orchestrator=object(),
        )
    )

    with pytest.raises(
        ApplicationStartupError,
        match=(
            "production state restorer "
            "is bound"
        ),
    ):
        StartupManager().start_runtime(
            runtime_startup=(
                runtime_startup
            ),
            started_at=NOW,
        )

    assert coordinator.calls == []


def test_shutdown_order_is_runtime_sessions_database():
    calls: list[str] = []

    persistence = cast(
        Any,
        SimpleNamespace(
            sessions=FakeSessions(
                calls
            ),
            database=FakeDatabase(
                calls
            ),
        ),
    )

    orchestrator = (
        FakeOrchestrator(
            state=(
                RuntimeState.RUNNING
            ),
            calls=calls,
        )
    )

    runtime_startup = (
        make_runtime_startup(
            recovery_required=False,
            state_restorer=object(),
            coordinator=(
                FakeStartupCoordinator()
            ),
            orchestrator=(
                orchestrator
            ),
            persistence=persistence,
        )
    )

    manager = ShutdownManager(
        runtime_startup=(
            runtime_startup
        ),
        persistence=persistence,
    )

    result = manager.shutdown(
        stopped_at=NOW
    )

    assert result.completed is True

    assert (
        result.runtime_stop_attempted
        is True
    )

    assert (
        result.runtime_state_before
        is RuntimeState.RUNNING
    )

    assert (
        result.runtime_state_after
        is RuntimeState.STOPPED
    )

    assert calls == [
        "orchestrator.stop",
        "sessions.stop",
        "database.dispose",
    ]


@pytest.mark.parametrize(
    "state",
    [
        RuntimeState.CREATED,
        RuntimeState.FAILED,
        RuntimeState.STOPPED,
    ],
)
def test_shutdown_skips_illegal_or_redundant_runtime_stop(
    state: RuntimeState,
) -> None:
    calls: list[str] = []

    persistence = cast(
        Any,
        SimpleNamespace(
            sessions=FakeSessions(
                calls
            ),
            database=FakeDatabase(
                calls
            ),
        ),
    )

    orchestrator = (
        FakeOrchestrator(
            state=state,
            calls=calls,
        )
    )

    runtime_startup = (
        make_runtime_startup(
            recovery_required=False,
            state_restorer=object(),
            coordinator=(
                FakeStartupCoordinator()
            ),
            orchestrator=(
                orchestrator
            ),
            persistence=persistence,
        )
    )

    result = ShutdownManager(
        runtime_startup=(
            runtime_startup
        ),
        persistence=persistence,
    ).shutdown(
        stopped_at=NOW
    )

    assert (
        result.runtime_stop_attempted
        is False
    )

    assert orchestrator.stop_calls == 0

    assert calls == [
        "sessions.stop",
        "database.dispose",
    ]

    assert result.sessions_stopped is True
    assert result.database_disposed is True


@pytest.mark.parametrize(
    "state",
    [
        RuntimeState.STARTING,
        RuntimeState.STOPPING,
    ],
)
def test_shutdown_refuses_transitional_runtime_state(
    state: RuntimeState,
) -> None:
    calls: list[str] = []

    persistence = cast(
        Any,
        SimpleNamespace(
            sessions=FakeSessions(
                calls
            ),
            database=FakeDatabase(
                calls
            ),
        ),
    )

    orchestrator = (
        FakeOrchestrator(
            state=state,
            calls=calls,
        )
    )

    runtime_startup = (
        make_runtime_startup(
            recovery_required=False,
            state_restorer=object(),
            coordinator=(
                FakeStartupCoordinator()
            ),
            orchestrator=(
                orchestrator
            ),
            persistence=persistence,
        )
    )

    with pytest.raises(
        ApplicationShutdownError,
        match="transitional state",
    ):
        ShutdownManager(
            runtime_startup=(
                runtime_startup
            ),
            persistence=persistence,
        ).shutdown(
            stopped_at=NOW
        )

    assert calls == []

    assert persistence.sessions.started is True
    assert persistence.database.started is True


def test_shutdown_is_idempotent_after_runtime_stopped():
    calls: list[str] = []

    persistence = cast(
        Any,
        SimpleNamespace(
            sessions=FakeSessions(
                calls,
                started=False,
            ),
            database=FakeDatabase(
                calls,
                started=False,
            ),
        ),
    )

    orchestrator = (
        FakeOrchestrator(
            state=(
                RuntimeState.STOPPED
            ),
            calls=calls,
        )
    )

    runtime_startup = (
        make_runtime_startup(
            recovery_required=False,
            state_restorer=object(),
            coordinator=(
                FakeStartupCoordinator()
            ),
            orchestrator=(
                orchestrator
            ),
            persistence=persistence,
        )
    )

    result = ShutdownManager(
        runtime_startup=(
            runtime_startup
        ),
        persistence=persistence,
    ).shutdown(
        stopped_at=NOW
    )

    assert result.completed is True
    assert calls == []