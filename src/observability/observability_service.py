"""
Phoenix M14 observability aggregation service.

The service reads the latest already-retained M08 runtime-health
snapshot and combines it with optional M14 metric/diagnostic
sources.

Important ownership rule:
    ObservabilityService never calls RuntimeHealthSupervisor.evaluate().
    Health evaluation and fail-closed runtime behavior remain M08-owned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.observability.observability_types import (
    ComponentHealthView,
    DiagnosticFinding,
    DiagnosticSeverity,
    MetricSample,
    MetricType,
    ObservabilitySnapshot,
    RuntimeHealthView,
)
from src.runtime.health_types import (
    RuntimeHealthSnapshot,
    RuntimeHealthStatus,
)


class RuntimeHealthSnapshotReader(
    Protocol,
):
    """
    Narrow read-only boundary over M08 RuntimeHealthSupervisor.
    """

    @property
    def latest_snapshot(
        self,
    ) -> RuntimeHealthSnapshot | None:
        ...


class MetricSource(
    Protocol,
):
    """
    Optional point-in-time M14 metric source.
    """

    def collect_metrics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[
        MetricSample,
        ...
    ]:
        ...


class DiagnosticSource(
    Protocol,
):
    """
    Optional point-in-time M14 diagnostic source.
    """

    def collect_diagnostics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[
        DiagnosticFinding,
        ...
    ]:
        ...


class ObservabilityService:
    """
    Aggregate passive operational observations.

    M14 derives read-only metrics/diagnostics from existing state.
    It does not mutate any subsystem and does not own health-check
    execution.
    """

    def __init__(
        self,
        *,
        runtime_health:
            RuntimeHealthSnapshotReader,
        metric_sources: tuple[
            MetricSource,
            ...
        ] = (),
        diagnostic_sources: tuple[
            DiagnosticSource,
            ...
        ] = (),
    ) -> None:
        self._runtime_health = (
            runtime_health
        )

        self._metric_sources = (
            tuple(
                metric_sources
            )
        )

        self._diagnostic_sources = (
            tuple(
                diagnostic_sources
            )
        )

    @property
    def runtime_health(
        self,
    ) -> RuntimeHealthSnapshotReader:
        return self._runtime_health

    @property
    def metric_sources(
        self,
    ) -> tuple[
        MetricSource,
        ...
    ]:
        return self._metric_sources

    @property
    def diagnostic_sources(
        self,
    ) -> tuple[
        DiagnosticSource,
        ...
    ]:
        return self._diagnostic_sources

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> ObservabilitySnapshot:
        """
        Capture one coherent M14 operational view.

        The latest M08 health snapshot is read once.
        """

        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be a datetime"
            )

        health_snapshot = (
            self._runtime_health
            .latest_snapshot
        )

        runtime_health = (
            self._project_runtime_health(
                health_snapshot
            )
            if health_snapshot is not None
            else None
        )

        metrics = list[
            MetricSample
        ](
            self._health_metrics(
                snapshot=health_snapshot,
                captured_at=captured_at,
            )
        )

        diagnostics = list[
            DiagnosticFinding
        ](
            self._health_diagnostics(
                snapshot=health_snapshot,
            )
        )

        for source in (
            self._metric_sources
        ):
            metrics.extend(
                source.collect_metrics(
                    captured_at=captured_at
                )
            )

        for source in (
            self._diagnostic_sources
        ):
            diagnostics.extend(
                source.collect_diagnostics(
                    captured_at=captured_at
                )
            )

        metrics.sort(
            key=lambda item: (
                item.name,
                item.labels,
                item.metric_type.value,
            )
        )

        diagnostics.sort(
            key=lambda item: (
                item.severity.value,
                item.code,
                item.component or "",
                item.message,
            )
        )

        return ObservabilitySnapshot(
            captured_at=captured_at,
            runtime_health=runtime_health,
            metrics=tuple(
                metrics
            ),
            diagnostics=tuple(
                diagnostics
            ),
        )

    @staticmethod
    def _project_runtime_health(
        snapshot: RuntimeHealthSnapshot,
    ) -> RuntimeHealthView:
        return RuntimeHealthView(
            status=snapshot.status.value,
            checked_at=snapshot.checked_at,
            components=tuple(
                ComponentHealthView(
                    component=(
                        component
                        .component
                        .value
                    ),
                    status=(
                        component
                        .status
                        .value
                    ),
                    checked_at=(
                        component
                        .checked_at
                    ),
                    critical=(
                        component
                        .critical
                    ),
                    message=(
                        component
                        .message
                    ),
                )
                for component
                in snapshot.components
            ),
        )

    @staticmethod
    def _health_metrics(
        *,
        snapshot:
            RuntimeHealthSnapshot
            | None,
        captured_at: datetime,
    ) -> tuple[
        MetricSample,
        ...
    ]:
        if snapshot is None:
            return ()

        healthy = 0
        degraded = 0
        failed = 0
        critical_failed = 0

        for component in (
            snapshot.components
        ):
            if (
                component.status
                is RuntimeHealthStatus.HEALTHY
            ):
                healthy += 1

            elif (
                component.status
                is RuntimeHealthStatus.DEGRADED
            ):
                degraded += 1

            elif (
                component.status
                is RuntimeHealthStatus.FAILED
            ):
                failed += 1

                if component.critical:
                    critical_failed += 1

        values = (
            (
                "phoenix.runtime.health.components.total",
                len(
                    snapshot.components
                ),
            ),
            (
                "phoenix.runtime.health.components.healthy",
                healthy,
            ),
            (
                "phoenix.runtime.health.components.degraded",
                degraded,
            ),
            (
                "phoenix.runtime.health.components.failed",
                failed,
            ),
            (
                "phoenix.runtime.health.components.critical_failed",
                critical_failed,
            ),
        )

        return tuple(
            MetricSample(
                name=name,
                metric_type=MetricType.GAUGE,
                value=float(value),
                captured_at=captured_at,
            )
            for name, value
            in values
        )

    @staticmethod
    def _health_diagnostics(
        *,
        snapshot:
            RuntimeHealthSnapshot
            | None,
    ) -> tuple[
        DiagnosticFinding,
        ...
    ]:
        if snapshot is None:
            return (
                DiagnosticFinding(
                    code=(
                        "M14_RUNTIME_HEALTH_UNAVAILABLE"
                    ),
                    severity=(
                        DiagnosticSeverity.WARNING
                    ),
                    message=(
                        "No retained runtime health "
                        "snapshot is currently available."
                    ),
                    component="RUNTIME",
                ),
            )

        findings: list[
            DiagnosticFinding
        ] = []

        for component in (
            snapshot.components
        ):
            if (
                component.status
                is RuntimeHealthStatus.DEGRADED
            ):
                findings.append(
                    DiagnosticFinding(
                        code=(
                            "M14_RUNTIME_COMPONENT_DEGRADED"
                        ),
                        severity=(
                            DiagnosticSeverity.WARNING
                        ),
                        message=(
                            component.message
                            or (
                                "Runtime component "
                                "is degraded."
                            )
                        ),
                        component=(
                            component
                            .component
                            .value
                        ),
                    )
                )

            elif (
                component.status
                is RuntimeHealthStatus.FAILED
            ):
                findings.append(
                    DiagnosticFinding(
                        code=(
                            "M14_RUNTIME_COMPONENT_FAILED"
                        ),
                        severity=(
                            DiagnosticSeverity.CRITICAL
                            if component.critical
                            else DiagnosticSeverity.ERROR
                        ),
                        message=(
                            component.message
                            or (
                                "Runtime component "
                                "health check failed."
                            )
                        ),
                        component=(
                            component
                            .component
                            .value
                        ),
                    )
                )

        return tuple(
            findings
        )


__all__ = [
    "DiagnosticSource",
    "MetricSource",
    "ObservabilityService",
    "RuntimeHealthSnapshotReader",
]
