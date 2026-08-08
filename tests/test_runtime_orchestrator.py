"""
Phoenix M08-T06 Trading Runtime Orchestrator tests.
"""

from datetime import (
    date,
    datetime,
    timedelta,
)

import pytest

from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.runtime_events import (
    RuntimeEventType,
)
from src.runtime.runtime_orchestrator import (
    DuplicateRuntimeComponentError,
    RuntimeTransitionError,
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeFailureCode,
    RuntimeId,
    RuntimeMode,
    RuntimeState,
)


TRADING_DATE = date(
    2026,
    8,
    8,
)

CREATED_AT = datetime(
    2026,
    8,
    8,
    8,
    45,
)

STARTED_AT = datetime(
    2026,
    8,
    8,
    9,
    0,
)

RUNNING_AT = datetime(
    2026,
    8,
    8,
    9,
    20,
)

STOPPED_AT = datetime(
    2026,
    8,
    8,
    15,
    16,
)


class FakeComponent:
    def __init__(
        self,
        name: str,
        calls: list[str],
        *,
        fail_start: bool = False,
        fail_stop: bool = False,
    ) -> None:
        self._name = name
        self._calls = calls
        self._fail_start = fail_start
        self._fail_stop = fail_stop

    @property
    def name(
        self,
    ) -> str:
        return self._name

    def start(
        self,
    ) -> None:
        self._calls.append(
            f"START:{self.name}"
        )

        if self._fail_start:
            raise RuntimeError(
                f"{self.name} start failed"
            )

    def stop(
        self,
    ) -> None:
        self._calls.append(
            f"STOP:{self.name}"
        )

        if self._fail_stop:
            raise RuntimeError(
                f"{self.name} stop failed"
            )


def make_runtime(
    *,
    mode: RuntimeMode = (
        RuntimeMode.DRY_RUN
    ),
    recovery_required: bool = False,
    event_bus: RuntimeEventBus | None = None,
):
    return TradingRuntimeOrchestrator(
        runtime_id=RuntimeId(
            "PHOENIX:2026-08-08:TEST"
        ),
        trading_date=TRADING_DATE,
        mode=mode,
        event_bus=(
            event_bus
            or RuntimeEventBus()
        ),
        created_at=CREATED_AT,
        recovery_required=recovery_required,
    )


# ============================================================
# Initial state
# ============================================================


def test_runtime_starts_created() -> None:
    runtime = make_runtime()

    assert (
        runtime.state
        is RuntimeState.CREATED
    )

    assert (
        runtime.snapshot.started_at
        is None
    )


def test_runtime_mode_preserved() -> None:
    runtime = make_runtime(
        mode=RuntimeMode.LIVE
    )

    assert (
        runtime.mode
        is RuntimeMode.LIVE
    )


def test_runtime_id_preserved() -> None:
    runtime = make_runtime()

    assert (
        runtime.runtime_id.value
        == "PHOENIX:2026-08-08:TEST"
    )


# ============================================================
# Component registration
# ============================================================


def test_register_component() -> None:
    runtime = make_runtime()

    calls = []

    component = FakeComponent(
        "database",
        calls,
    )

    runtime.register_component(
        component=component,
        order=10,
    )

    components = (
        runtime.registered_components()
    )

    assert len(components) == 1

    assert (
        components[0].name
        == "database"
    )


def test_components_sorted_by_order() -> None:
    runtime = make_runtime()

    calls = []

    runtime.register_component(
        component=FakeComponent(
            "market",
            calls,
        ),
        order=30,
    )

    runtime.register_component(
        component=FakeComponent(
            "database",
            calls,
        ),
        order=10,
    )

    runtime.register_component(
        component=FakeComponent(
            "persistence",
            calls,
        ),
        order=20,
    )

    names = [
        item.name
        for item
        in runtime.registered_components()
    ]

    assert names == [
        "database",
        "persistence",
        "market",
    ]


def test_duplicate_component_rejected() -> None:
    runtime = make_runtime()

    calls = []

    runtime.register_component(
        component=FakeComponent(
            "database",
            calls,
        ),
        order=10,
    )

    with pytest.raises(
        DuplicateRuntimeComponentError
    ):
        runtime.register_component(
            component=FakeComponent(
                "database",
                calls,
            ),
            order=20,
        )


def test_negative_component_order_rejected() -> None:
    runtime = make_runtime()

    with pytest.raises(
        ValueError,
        match=(
            "runtime component order "
            "cannot be negative"
        ),
    ):
        runtime.register_component(
            component=FakeComponent(
                "database",
                [],
            ),
            order=-1,
        )


def test_component_registration_blocked_after_start() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    with pytest.raises(
        RuntimeTransitionError,
        match=(
            "registered while runtime is CREATED"
        ),
    ):
        runtime.register_component(
            component=FakeComponent(
                "late",
                [],
            ),
            order=99,
        )


# ============================================================
# Startup
# ============================================================


def test_clean_start_reaches_ready() -> None:
    runtime = make_runtime()

    result = runtime.start(
        started_at=STARTED_AT
    )

    assert (
        result.state
        is RuntimeState.READY
    )

    assert (
        result.started_at
        == STARTED_AT
    )


def test_start_components_in_order() -> None:
    runtime = make_runtime()

    calls = []

    runtime.register_component(
        component=FakeComponent(
            "market",
            calls,
        ),
        order=30,
    )

    runtime.register_component(
        component=FakeComponent(
            "database",
            calls,
        ),
        order=10,
    )

    runtime.register_component(
        component=FakeComponent(
            "repositories",
            calls,
        ),
        order=20,
    )

    runtime.start(
        started_at=STARTED_AT
    )

    assert calls == [
        "START:database",
        "START:repositories",
        "START:market",
    ]


def test_start_publishes_lifecycle_events() -> None:
    events = []

    bus = RuntimeEventBus()

    def capture(event):
        events.append(
            event.event_type
        )

    bus.subscribe(
        RuntimeEventType.RUNTIME_STARTED,
        capture,
    )

    bus.subscribe(
        RuntimeEventType.RUNTIME_READY,
        capture,
    )

    runtime = make_runtime(
        event_bus=bus
    )

    runtime.start(
        started_at=STARTED_AT
    )

    assert events == [
        RuntimeEventType.RUNTIME_STARTED,
        RuntimeEventType.RUNTIME_READY,
    ]


def test_second_start_rejected() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    with pytest.raises(
        RuntimeTransitionError,
        match=(
            "runtime can only start "
            "from CREATED"
        ),
    ):
        runtime.start(
            started_at=STARTED_AT
        )


# ============================================================
# Recovery startup
# ============================================================


def test_recovery_start_enters_recovering() -> None:
    runtime = make_runtime(
        recovery_required=True
    )

    result = runtime.start(
        started_at=STARTED_AT
    )

    assert (
        result.state
        is RuntimeState.RECOVERING
    )

    assert (
        result.recovery_required
        is True
    )


def test_recovery_start_blocks_entries() -> None:
    runtime = make_runtime(
        recovery_required=True
    )

    runtime.start(
        started_at=STARTED_AT
    )

    assert (
        runtime.can_accept_new_entries()
        is False
    )

    assert (
        runtime.live_execution_allowed()
        is False
    )


def test_complete_recovery_reaches_ready() -> None:
    runtime = make_runtime(
        recovery_required=True
    )

    runtime.start(
        started_at=STARTED_AT
    )

    completed_at = (
        STARTED_AT
        + timedelta(seconds=10)
    )

    result = runtime.complete_recovery(
        completed_at=completed_at
    )

    assert (
        result.state
        is RuntimeState.READY
    )

    assert (
        result.recovery_required
        is False
    )

    assert result.recovered is True


def test_complete_recovery_requires_recovering_state() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    with pytest.raises(
        RuntimeTransitionError,
        match=(
            "recovery can only complete "
            "from RECOVERING"
        ),
    ):
        runtime.complete_recovery(
            completed_at=RUNNING_AT
        )


# ============================================================
# Running
# ============================================================


def test_ready_runtime_can_run() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    result = runtime.run(
        running_at=RUNNING_AT
    )

    assert (
        result.state
        is RuntimeState.RUNNING
    )


def test_running_runtime_processes_market_data() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    runtime.run(
        running_at=RUNNING_AT
    )

    assert (
        runtime.can_process_market_data()
        is True
    )


def test_running_runtime_accepts_new_entries() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    runtime.run(
        running_at=RUNNING_AT
    )

    assert (
        runtime.can_accept_new_entries()
        is True
    )


def test_run_before_ready_rejected() -> None:
    runtime = make_runtime()

    with pytest.raises(
        RuntimeTransitionError,
        match=(
            "runtime can only run from READY"
        ),
    ):
        runtime.run(
            running_at=RUNNING_AT
        )


# ============================================================
# Execution mode
# ============================================================


def test_dry_run_never_allows_live_execution() -> None:
    runtime = make_runtime(
        mode=RuntimeMode.DRY_RUN
    )

    runtime.start(
        started_at=STARTED_AT
    )

    runtime.run(
        running_at=RUNNING_AT
    )

    assert (
        runtime.live_execution_allowed()
        is False
    )


def test_live_running_runtime_allows_live_execution() -> None:
    runtime = make_runtime(
        mode=RuntimeMode.LIVE
    )

    runtime.start(
        started_at=STARTED_AT
    )

    runtime.run(
        running_at=RUNNING_AT
    )

    assert (
        runtime.live_execution_allowed()
        is True
    )


def test_live_ready_runtime_does_not_allow_execution() -> None:
    runtime = make_runtime(
        mode=RuntimeMode.LIVE
    )

    runtime.start(
        started_at=STARTED_AT
    )

    assert (
        runtime.live_execution_allowed()
        is False
    )


# ============================================================
# Startup failure
# ============================================================


def test_start_failure_moves_runtime_to_failed() -> None:
    runtime = make_runtime()

    runtime.register_component(
        component=FakeComponent(
            "database",
            [],
            fail_start=True,
        ),
        order=10,
    )

    result = runtime.start(
        started_at=STARTED_AT
    )

    assert (
        result.state
        is RuntimeState.FAILED
    )

    assert result.failure is not None

    assert (
        result.failure.code
        is RuntimeFailureCode.STARTUP_FAILED
    )


def test_start_failure_rolls_back_started_components() -> None:
    runtime = make_runtime()

    calls = []

    runtime.register_component(
        component=FakeComponent(
            "database",
            calls,
        ),
        order=10,
    )

    runtime.register_component(
        component=FakeComponent(
            "market",
            calls,
            fail_start=True,
        ),
        order=20,
    )

    runtime.start(
        started_at=STARTED_AT
    )

    assert calls == [
        "START:database",
        "START:market",
        "STOP:database",
    ]


def test_failed_runtime_blocks_entries() -> None:
    runtime = make_runtime(
        mode=RuntimeMode.LIVE
    )

    runtime.fail(
        code=(
            RuntimeFailureCode
            .DATABASE_FAILED
        ),
        message="database failed",
        failed_at=STARTED_AT,
        component="database",
    )

    assert (
        runtime.can_accept_new_entries()
        is False
    )

    assert (
        runtime.live_execution_allowed()
        is False
    )


# ============================================================
# Shutdown
# ============================================================


def test_running_runtime_can_stop() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    runtime.run(
        running_at=RUNNING_AT
    )

    result = runtime.stop(
        stopped_at=STOPPED_AT
    )

    assert (
        result.state
        is RuntimeState.STOPPED
    )

    assert (
        result.stopped_at
        == STOPPED_AT
    )


def test_stop_components_in_reverse_order() -> None:
    runtime = make_runtime()

    calls = []

    runtime.register_component(
        component=FakeComponent(
            "database",
            calls,
        ),
        order=10,
    )

    runtime.register_component(
        component=FakeComponent(
            "repositories",
            calls,
        ),
        order=20,
    )

    runtime.register_component(
        component=FakeComponent(
            "market",
            calls,
        ),
        order=30,
    )

    runtime.start(
        started_at=STARTED_AT
    )

    calls.clear()

    runtime.run(
        running_at=RUNNING_AT
    )

    runtime.stop(
        stopped_at=STOPPED_AT
    )

    assert calls == [
        "STOP:market",
        "STOP:repositories",
        "STOP:database",
    ]


def test_stop_publishes_events() -> None:
    events = []

    bus = RuntimeEventBus()

    def capture(event):
        events.append(
            event.event_type
        )

    bus.subscribe(
        RuntimeEventType.RUNTIME_STOPPING,
        capture,
    )

    bus.subscribe(
        RuntimeEventType.RUNTIME_STOPPED,
        capture,
    )

    runtime = make_runtime(
        event_bus=bus
    )

    runtime.start(
        started_at=STARTED_AT
    )

    runtime.run(
        running_at=RUNNING_AT
    )

    runtime.stop(
        stopped_at=STOPPED_AT
    )

    assert events == [
        RuntimeEventType.RUNTIME_STOPPING,
        RuntimeEventType.RUNTIME_STOPPED,
    ]


def test_stop_from_created_rejected() -> None:
    runtime = make_runtime()

    with pytest.raises(
        RuntimeTransitionError
    ):
        runtime.stop(
            stopped_at=STOPPED_AT
        )


def test_shutdown_failure_moves_runtime_to_failed() -> None:
    runtime = make_runtime()

    runtime.register_component(
        component=FakeComponent(
            "database",
            [],
            fail_stop=True,
        ),
        order=10,
    )

    runtime.start(
        started_at=STARTED_AT
    )

    runtime.run(
        running_at=RUNNING_AT
    )

    result = runtime.stop(
        stopped_at=STOPPED_AT
    )

    assert (
        result.state
        is RuntimeState.FAILED
    )

    assert result.failure is not None

    assert (
        result.failure.code
        is RuntimeFailureCode.SHUTDOWN_FAILED
    )


# ============================================================
# Explicit failure
# ============================================================


def test_fail_runtime() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    result = runtime.fail(
        code=(
            RuntimeFailureCode
            .MARKET_DATA_FAILED
        ),
        message="feed disconnected",
        failed_at=RUNNING_AT,
        component="market-data",
        recoverable=True,
    )

    assert (
        result.state
        is RuntimeState.FAILED
    )

    assert (
        result.recovery_required
        is True
    )

    assert result.failure is not None

    assert (
        result.failure.component
        == "market-data"
    )


def test_stopped_runtime_cannot_fail() -> None:
    runtime = make_runtime()

    runtime.start(
        started_at=STARTED_AT
    )

    runtime.run(
        running_at=RUNNING_AT
    )

    runtime.stop(
        stopped_at=STOPPED_AT
    )

    with pytest.raises(
        RuntimeTransitionError,
        match=(
            "STOPPED runtime cannot transition "
            "to FAILED"
        ),
    ):
        runtime.fail(
            code=(
                RuntimeFailureCode
                .INTERNAL_ERROR
            ),
            message="late failure",
            failed_at=STOPPED_AT,
        )