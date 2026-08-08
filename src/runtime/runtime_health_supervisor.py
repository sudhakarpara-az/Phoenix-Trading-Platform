"""
Phoenix M08 runtime health supervision.

Responsibilities:
    - run registered health checks
    - aggregate runtime health
    - fail closed on critical failures
    - classify failures for TradingRuntimeOrchestrator
    - publish HEALTH_CHANGED events
    - preserve deterministic evaluation order

No component repair/restart logic belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from src.runtime.event_bus import (
    RuntimeEventBus,
    RuntimeEventDispatchError,
)
from src.runtime.health_types import (
    ComponentHealthResult,
    RuntimeHealthCheck,
    RuntimeHealthComponent,
    RuntimeHealthSnapshot,
    RuntimeHealthStatus,
)
from src.runtime.runtime_events import (
    RuntimeEvent,
    RuntimeEventType,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeFailureCode,
    RuntimeState,
)


@dataclass(
    frozen=True,
    slots=True,
)
class RegisteredHealthCheck:
    check: RuntimeHealthCheck

    order: int

    @property
    def component(
        self,
    ) -> RuntimeHealthComponent:
        return self.check.component


class DuplicateHealthCheckError(
    ValueError
):
    pass


class RuntimeHealthSupervisor:
    """
    Supervises health of critical Phoenix runtime dependencies.
    """

    def __init__(
        self,
        *,
        orchestrator:
            TradingRuntimeOrchestrator,
        event_bus:
            RuntimeEventBus,
    ) -> None:
        self._orchestrator = orchestrator
        self._event_bus = event_bus

        self._checks: dict[
            RuntimeHealthComponent,
            RegisteredHealthCheck,
        ] = {}

        self._latest_snapshot: (
            RuntimeHealthSnapshot
            | None
        ) = None

        self._lock = RLock()

    @property
    def latest_snapshot(
        self,
    ) -> RuntimeHealthSnapshot | None:
        with self._lock:
            return self._latest_snapshot

    def register_check(
        self,
        *,
        check: RuntimeHealthCheck,
        order: int,
    ) -> None:
        if order < 0:
            raise ValueError(
                "health check order cannot be negative"
            )

        component = check.component

        with self._lock:
            if component in self._checks:
                raise DuplicateHealthCheckError(
                    "health check already registered: "
                    f"{component.value}"
                )

            self._checks[
                component
            ] = RegisteredHealthCheck(
                check=check,
                order=order,
            )

    def registered_checks(
        self,
    ) -> tuple[
        RegisteredHealthCheck,
        ...
    ]:
        with self._lock:
            return tuple(
                sorted(
                    self._checks.values(),
                    key=lambda item: (
                        item.order,
                        item.component.value,
                    ),
                )
            )

    def evaluate(
        self,
        *,
        checked_at: datetime,
    ) -> RuntimeHealthSnapshot:
        """
        Run all checks and fail the runtime on critical failure.
        """

        results: list[
            ComponentHealthResult
        ] = []

        for registration in (
            self.registered_checks()
        ):
            check = registration.check

            try:
                result = check.check(
                    checked_at=checked_at
                )

            except Exception as exc:
                result = ComponentHealthResult(
                    component=check.component,
                    status=(
                        RuntimeHealthStatus.FAILED
                    ),
                    checked_at=checked_at,
                    message=(
                        "health check raised exception: "
                        f"{exc}"
                    ),
                    critical=check.critical,
                )

            if (
                result.component
                is not check.component
            ):
                result = ComponentHealthResult(
                    component=check.component,
                    status=(
                        RuntimeHealthStatus.FAILED
                    ),
                    checked_at=checked_at,
                    message=(
                        "health check returned mismatched "
                        "component identity"
                    ),
                    critical=True,
                )

            results.append(
                result
            )

        snapshot = (
            self._aggregate(
                results=tuple(
                    results
                ),
                checked_at=checked_at,
            )
        )

        with self._lock:
            previous = (
                self._latest_snapshot
            )

            self._latest_snapshot = snapshot

        if (
            previous is None
            or previous.status
            is not snapshot.status
        ):
            self._publish_health_change(
                snapshot
            )

        critical_failure = next(
            (
                item
                for item in snapshot.components
                if (
                    item.status
                    is RuntimeHealthStatus.FAILED
                    and item.critical
                )
            ),
            None,
        )

        if (
            critical_failure is not None
            and self._orchestrator.state
            not in {
                RuntimeState.FAILED,
                RuntimeState.STOPPED,
            }
        ):
            self._orchestrator.fail(
                code=(
                    self._failure_code_for_component(
                        critical_failure.component
                    )
                ),
                message=(
                    critical_failure.message
                    or (
                        "critical runtime health "
                        "check failed"
                    )
                ),
                failed_at=checked_at,
                component=(
                    critical_failure
                    .component.value
                ),
                recoverable=(
                    critical_failure.component
                    in {
                        RuntimeHealthComponent
                        .DATABASE,
                        RuntimeHealthComponent
                        .MARKET_DATA,
                        RuntimeHealthComponent
                        .RECOVERY,
                    }
                ),
            )

        return snapshot

    @staticmethod
    def _aggregate(
        *,
        results: tuple[
            ComponentHealthResult,
            ...
        ],
        checked_at: datetime,
    ) -> RuntimeHealthSnapshot:
        if any(
            item.status
            is RuntimeHealthStatus.FAILED
            for item in results
        ):
            status = (
                RuntimeHealthStatus.FAILED
            )

        elif any(
            item.status
            is RuntimeHealthStatus.DEGRADED
            for item in results
        ):
            status = (
                RuntimeHealthStatus.DEGRADED
            )

        else:
            status = (
                RuntimeHealthStatus.HEALTHY
            )

        return RuntimeHealthSnapshot(
            status=status,
            checked_at=checked_at,
            components=results,
        )

    def _publish_health_change(
        self,
        snapshot:
            RuntimeHealthSnapshot,
    ) -> None:
        event = RuntimeEvent.create(
            runtime_id=(
                self._orchestrator
                .runtime_id
            ),
            event_type=(
                RuntimeEventType
                .HEALTH_CHANGED
            ),
            occurred_at=(
                snapshot.checked_at
            ),
            payload={
                "status": (
                    snapshot.status.value
                ),
                "components": [
                    {
                        "component": (
                            item.component.value
                        ),
                        "status": (
                            item.status.value
                        ),
                        "critical": (
                            item.critical
                        ),
                        "message": (
                            item.message
                        ),
                    }
                    for item
                    in snapshot.components
                ],
            },
            correlation_id=(
                self._orchestrator
                .runtime_id.value
            ),
        )

        try:
            self._event_bus.publish(
                event
            )

        except RuntimeEventDispatchError:
            # Health truth remains authoritative even if an
            # observer/audit subscriber itself fails.
            pass

    @staticmethod
    def _failure_code_for_component(
        component:
            RuntimeHealthComponent,
    ) -> RuntimeFailureCode:
        mapping = {
            RuntimeHealthComponent.DATABASE:
                RuntimeFailureCode
                .DATABASE_FAILED,

            RuntimeHealthComponent.MARKET_DATA:
                RuntimeFailureCode
                .MARKET_DATA_FAILED,

            RuntimeHealthComponent.RECOVERY:
                RuntimeFailureCode
                .RECOVERY_FAILED,

            RuntimeHealthComponent.EXECUTION:
                RuntimeFailureCode
                .EXECUTION_FAILED,

            RuntimeHealthComponent.RISK:
                RuntimeFailureCode
                .RISK_FAILED,

            RuntimeHealthComponent.INTERNAL:
                RuntimeFailureCode
                .HEALTH_CHECK_FAILED,
        }

        return mapping[
            component
        ]
class DatabaseHealthCheck:
    def __init__(
        self,
        *,
        database_engine,
        critical: bool = True,
    ) -> None:
        self._database_engine = (
            database_engine
        )

        self._critical = critical

    @property
    def component(
        self,
    ) -> RuntimeHealthComponent:
        return (
            RuntimeHealthComponent.DATABASE
        )

    @property
    def critical(
        self,
    ) -> bool:
        return self._critical

    def check(
        self,
        *,
        checked_at: datetime,
    ) -> ComponentHealthResult:
        healthy = (
            self._database_engine
            .health_check()
        )

        return ComponentHealthResult(
            component=self.component,
            status=(
                RuntimeHealthStatus.HEALTHY
                if healthy
                else RuntimeHealthStatus.FAILED
            ),
            checked_at=checked_at,
            message=(
                None
                if healthy
                else "database health check failed"
            ),
            critical=self.critical,
        )


class RecoveryHealthCheck:
    """
    Reports whether runtime recovery remains unresolved.
    """

    def __init__(
        self,
        *,
        orchestrator:
            TradingRuntimeOrchestrator,
        critical: bool = True,
    ) -> None:
        self._orchestrator = orchestrator
        self._critical = critical

    @property
    def component(
        self,
    ) -> RuntimeHealthComponent:
        return (
            RuntimeHealthComponent.RECOVERY
        )

    @property
    def critical(
        self,
    ) -> bool:
        return self._critical

    def check(
        self,
        *,
        checked_at: datetime,
    ) -> ComponentHealthResult:
        snapshot = (
            self._orchestrator.snapshot
        )

        if (
            snapshot.state
            is RuntimeState.FAILED
            and snapshot.failure is not None
            and snapshot.failure.code
            is RuntimeFailureCode.RECOVERY_FAILED
        ):
            return ComponentHealthResult(
                component=self.component,
                status=(
                    RuntimeHealthStatus.FAILED
                ),
                checked_at=checked_at,
                message=(
                    snapshot.failure.message
                ),
                critical=self.critical,
            )

        if snapshot.recovery_required:
            return ComponentHealthResult(
                component=self.component,
                status=(
                    RuntimeHealthStatus.DEGRADED
                ),
                checked_at=checked_at,
                message=(
                    "runtime recovery is still required"
                ),
                critical=self.critical,
            )

        return ComponentHealthResult(
            component=self.component,
            status=(
                RuntimeHealthStatus.HEALTHY
            ),
            checked_at=checked_at,
            critical=self.critical,
        )    