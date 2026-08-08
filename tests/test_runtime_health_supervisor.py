"""
Phoenix M08-T09 Runtime Health & Failure Supervision tests.
"""

from datetime import (
    date,
    datetime,
)

import pytest

from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.health_types import (
    ComponentHealthResult,
    RuntimeHealthComponent,
    RuntimeHealthStatus,
)
from src.runtime.runtime_events import (
    RuntimeEventType,
)
from src.runtime.runtime_health_supervisor import (
    DatabaseHealthCheck,
    DuplicateHealthCheckError,
    RecoveryHealthCheck,
    RuntimeHealthSupervisor,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeFailureCode,
    RuntimeId,
    RuntimeMode,
    RuntimeState,
)


TODAY = date(
    2026,
    8,
    8,
)

NOW = datetime(
    2026,
    8,
    8,
    13,
    30,
)


class FakeHealthCheck:
    def __init__(
        self,
        *,
        component,
        status,
        critical=True,
        message=None,
        raises=None,
    ):
        self._component = component
        self._status = status
        self._critical = critical
        self._message = message
        self._raises = raises

    @property
    def component(self):
        return self._component

    @property
    def critical(self):
        return self._critical

    def check(
        self,
        *,
        checked_at,
    ):
        if self._raises is not None:
            raise self._raises

        return ComponentHealthResult(
            component=self._component,
            status=self._status,
            checked_at=checked_at,
            message=self._message,
            critical=self._critical,
        )


def make_runtime(
    *,
    recovery_required=False,
):
    runtime = TradingRuntimeOrchestrator(
        runtime_id=RuntimeId(
            "PHOENIX-HEALTH"
        ),
        trading_date=TODAY,
        mode=RuntimeMode.LIVE,
        event_bus=RuntimeEventBus(),
        created_at=NOW,
        recovery_required=recovery_required,
    )

    runtime.start(
        started_at=NOW
    )

    if not recovery_required:
        runtime.run(
            running_at=NOW
        )

    return runtime


def make_supervisor(
    runtime=None,
    bus=None,
):
    runtime = (
        runtime
        or make_runtime()
    )

    bus = (
        bus
        or RuntimeEventBus()
    )

    return RuntimeHealthSupervisor(
        orchestrator=runtime,
        event_bus=bus,
    )


# ============================================================
# Registration
# ============================================================


def test_register_health_check():
    supervisor = make_supervisor()

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent
                .DATABASE
            ),
            status=(
                RuntimeHealthStatus
                .HEALTHY
            ),
        ),
        order=10,
    )

    assert len(
        supervisor.registered_checks()
    ) == 1


def test_duplicate_health_check_rejected():
    supervisor = make_supervisor()

    first = FakeHealthCheck(
        component=(
            RuntimeHealthComponent.DATABASE
        ),
        status=(
            RuntimeHealthStatus.HEALTHY
        ),
    )

    second = FakeHealthCheck(
        component=(
            RuntimeHealthComponent.DATABASE
        ),
        status=(
            RuntimeHealthStatus.HEALTHY
        ),
    )

    supervisor.register_check(
        check=first,
        order=10,
    )

    with pytest.raises(
        DuplicateHealthCheckError
    ):
        supervisor.register_check(
            check=second,
            order=20,
        )


def test_negative_health_order_rejected():
    supervisor = make_supervisor()

    with pytest.raises(
        ValueError,
        match=(
            "health check order cannot be negative"
        ),
    ):
        supervisor.register_check(
            check=FakeHealthCheck(
                component=(
                    RuntimeHealthComponent
                    .DATABASE
                ),
                status=(
                    RuntimeHealthStatus
                    .HEALTHY
                ),
            ),
            order=-1,
        )


# ============================================================
# Aggregate health
# ============================================================


def test_all_healthy_returns_healthy():
    runtime = make_runtime()
    supervisor = make_supervisor(
        runtime=runtime
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent
                .DATABASE
            ),
            status=(
                RuntimeHealthStatus
                .HEALTHY
            ),
        ),
        order=10,
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent
                .MARKET_DATA
            ),
            status=(
                RuntimeHealthStatus
                .HEALTHY
            ),
        ),
        order=20,
    )

    snapshot = supervisor.evaluate(
        checked_at=NOW
    )

    assert (
        snapshot.status
        is RuntimeHealthStatus.HEALTHY
    )

    assert snapshot.healthy is True

    assert (
        runtime.state
        is RuntimeState.RUNNING
    )


def test_degraded_component_returns_degraded():
    runtime = make_runtime()

    supervisor = make_supervisor(
        runtime=runtime
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent
                .MARKET_DATA
            ),
            status=(
                RuntimeHealthStatus
                .DEGRADED
            ),
            critical=True,
            message="feed delayed",
        ),
        order=10,
    )

    snapshot = supervisor.evaluate(
        checked_at=NOW
    )

    assert (
        snapshot.status
        is RuntimeHealthStatus.DEGRADED
    )

    assert (
        runtime.state
        is RuntimeState.RUNNING
    )


def test_critical_failure_fails_runtime():
    runtime = make_runtime()

    supervisor = make_supervisor(
        runtime=runtime
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent
                .DATABASE
            ),
            status=(
                RuntimeHealthStatus
                .FAILED
            ),
            critical=True,
            message="database unavailable",
        ),
        order=10,
    )

    snapshot = supervisor.evaluate(
        checked_at=NOW
    )

    assert (
        snapshot.status
        is RuntimeHealthStatus.FAILED
    )

    assert (
        runtime.state
        is RuntimeState.FAILED
    )

    assert runtime.snapshot.failure is not None

    assert (
        runtime.snapshot.failure.code
        is RuntimeFailureCode
        .DATABASE_FAILED
    )


def test_noncritical_failure_does_not_fail_runtime():
    runtime = make_runtime()

    supervisor = make_supervisor(
        runtime=runtime
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent
                .INTERNAL
            ),
            status=(
                RuntimeHealthStatus
                .FAILED
            ),
            critical=False,
            message="telemetry unavailable",
        ),
        order=10,
    )

    snapshot = supervisor.evaluate(
        checked_at=NOW
    )

    assert (
        snapshot.status
        is RuntimeHealthStatus.FAILED
    )

    assert (
        runtime.state
        is RuntimeState.RUNNING
    )


# ============================================================
# Exception handling
# ============================================================


def test_health_check_exception_becomes_failure():
    runtime = make_runtime()

    supervisor = make_supervisor(
        runtime=runtime
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent.RISK
            ),
            status=(
                RuntimeHealthStatus.HEALTHY
            ),
            raises=RuntimeError(
                "risk engine unavailable"
            ),
        ),
        order=10,
    )

    snapshot = supervisor.evaluate(
        checked_at=NOW
    )

    assert (
        snapshot.status
        is RuntimeHealthStatus.FAILED
    )

    assert (
        runtime.state
        is RuntimeState.FAILED
    )

    assert (
        runtime.snapshot.failure.code
        is RuntimeFailureCode.RISK_FAILED
    )


# ============================================================
# Event publication
# ============================================================


def test_health_change_event_published():
    runtime = make_runtime()

    bus = RuntimeEventBus()

    events = []

    def capture(event):
        events.append(
            event
        )

    bus.subscribe(
        RuntimeEventType.HEALTH_CHANGED,
        capture,
    )

    supervisor = make_supervisor(
        runtime=runtime,
        bus=bus,
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent.DATABASE
            ),
            status=(
                RuntimeHealthStatus.HEALTHY
            ),
        ),
        order=10,
    )

    supervisor.evaluate(
        checked_at=NOW
    )

    assert len(events) == 1

    assert (
        events[0].event_type
        is RuntimeEventType.HEALTH_CHANGED
    )

    assert (
        events[0].payload["status"]
        == "HEALTHY"
    )


def test_same_health_status_not_republished():
    runtime = make_runtime()

    bus = RuntimeEventBus()

    events = []

    bus.subscribe(
        RuntimeEventType.HEALTH_CHANGED,
        lambda event: events.append(
            event
        ),
    )

    supervisor = make_supervisor(
        runtime=runtime,
        bus=bus,
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent.DATABASE
            ),
            status=(
                RuntimeHealthStatus.HEALTHY
            ),
        ),
        order=10,
    )

    supervisor.evaluate(
        checked_at=NOW
    )

    supervisor.evaluate(
        checked_at=NOW
    )

    assert len(events) == 1


# ============================================================
# Database adapter
# ============================================================


def test_database_health_check_healthy():
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    database.start()

    check = DatabaseHealthCheck(
        database_engine=database
    )

    result = check.check(
        checked_at=NOW
    )

    assert (
        result.status
        is RuntimeHealthStatus.HEALTHY
    )

    database.dispose()


def test_database_health_check_failure():
    class BrokenDatabase:
        def health_check(self):
            return False

    check = DatabaseHealthCheck(
        database_engine=(
            BrokenDatabase()
        )
    )

    result = check.check(
        checked_at=NOW
    )

    assert (
        result.status
        is RuntimeHealthStatus.FAILED
    )


# ============================================================
# Recovery adapter
# ============================================================


def test_recovery_health_is_degraded_while_required():
    runtime = make_runtime(
        recovery_required=True
    )

    assert (
        runtime.state
        is RuntimeState.RECOVERING
    )

    check = RecoveryHealthCheck(
        orchestrator=runtime
    )

    result = check.check(
        checked_at=NOW
    )

    assert (
        result.status
        is RuntimeHealthStatus.DEGRADED
    )


def test_recovery_health_is_healthy_after_recovery():
    runtime = make_runtime(
        recovery_required=True
    )

    runtime.complete_recovery(
        completed_at=NOW
    )

    check = RecoveryHealthCheck(
        orchestrator=runtime
    )

    result = check.check(
        checked_at=NOW
    )

    assert (
        result.status
        is RuntimeHealthStatus.HEALTHY
    )


# ============================================================
# Runtime gates after failure
# ============================================================


def test_database_failure_blocks_new_entries():
    runtime = make_runtime()

    supervisor = make_supervisor(
        runtime=runtime
    )

    supervisor.register_check(
        check=FakeHealthCheck(
            component=(
                RuntimeHealthComponent.DATABASE
            ),
            status=(
                RuntimeHealthStatus.FAILED
            ),
            critical=True,
            message="database unavailable",
        ),
        order=10,
    )

    supervisor.evaluate(
        checked_at=NOW
    )

    assert (
        runtime.can_accept_new_entries()
        is False
    )

    assert (
        runtime.live_execution_allowed()
        is False
    )