from datetime import datetime

from src.observability.observability_service import (
    ObservabilityService,
)
from src.observability.observability_types import (
    DiagnosticFinding,
    DiagnosticSeverity,
    MetricSample,
    MetricType,
)
from src.runtime.health_types import (
    ComponentHealthResult,
    RuntimeHealthComponent,
    RuntimeHealthSnapshot,
    RuntimeHealthStatus,
)


NOW = datetime(
    2026,
    8,
    30,
    10,
    35,
)


class FakeHealthReader:
    def __init__(
        self,
        snapshot:
            RuntimeHealthSnapshot
            | None,
    ) -> None:
        self._snapshot = snapshot
        self.read_count = 0

    @property
    def latest_snapshot(
        self,
    ) -> RuntimeHealthSnapshot | None:
        self.read_count += 1
        return self._snapshot


class FakeMetricSource:
    def collect_metrics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[
        MetricSample,
        ...
    ]:
        return (
            MetricSample(
                name="phoenix.custom.metric",
                metric_type=MetricType.GAUGE,
                value=7.0,
                captured_at=captured_at,
            ),
        )


class FakeDiagnosticSource:
    def collect_diagnostics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[
        DiagnosticFinding,
        ...
    ]:
        assert captured_at == NOW

        return (
            DiagnosticFinding(
                code="CUSTOM_DIAGNOSTIC",
                severity=DiagnosticSeverity.INFO,
                message="custom diagnostic",
            ),
        )


def make_health_snapshot() -> RuntimeHealthSnapshot:
    return RuntimeHealthSnapshot(
        status=RuntimeHealthStatus.FAILED,
        checked_at=NOW,
        components=(
            ComponentHealthResult(
                component=(
                    RuntimeHealthComponent.DATABASE
                ),
                status=(
                    RuntimeHealthStatus.HEALTHY
                ),
                checked_at=NOW,
                critical=True,
            ),
            ComponentHealthResult(
                component=(
                    RuntimeHealthComponent.MARKET_DATA
                ),
                status=(
                    RuntimeHealthStatus.DEGRADED
                ),
                checked_at=NOW,
                message="market feed delayed",
                critical=True,
            ),
            ComponentHealthResult(
                component=(
                    RuntimeHealthComponent.EXECUTION
                ),
                status=(
                    RuntimeHealthStatus.FAILED
                ),
                checked_at=NOW,
                message="execution unavailable",
                critical=True,
            ),
        ),
    )


def test_capture_reads_retained_health_once() -> None:
    reader = FakeHealthReader(
        make_health_snapshot()
    )

    service = ObservabilityService(
        runtime_health=reader
    )

    snapshot = service.capture(
        captured_at=NOW
    )

    assert reader.read_count == 1
    assert snapshot.runtime_health is not None
    assert (
        snapshot.runtime_health.status
        == "FAILED"
    )
    assert len(
        snapshot.runtime_health.components
    ) == 3


def test_capture_derives_health_metrics() -> None:
    service = ObservabilityService(
        runtime_health=FakeHealthReader(
            make_health_snapshot()
        )
    )

    snapshot = service.capture(
        captured_at=NOW
    )

    metrics = {
        metric.name: metric.value
        for metric in snapshot.metrics
    }

    assert (
        metrics[
            "phoenix.runtime.health.components.total"
        ]
        == 3.0
    )

    assert (
        metrics[
            "phoenix.runtime.health.components.healthy"
        ]
        == 1.0
    )

    assert (
        metrics[
            "phoenix.runtime.health.components.degraded"
        ]
        == 1.0
    )

    assert (
        metrics[
            "phoenix.runtime.health.components.failed"
        ]
        == 1.0
    )

    assert (
        metrics[
            "phoenix.runtime.health.components.critical_failed"
        ]
        == 1.0
    )


def test_capture_projects_degraded_and_failed_diagnostics() -> None:
    service = ObservabilityService(
        runtime_health=FakeHealthReader(
            make_health_snapshot()
        )
    )

    snapshot = service.capture(
        captured_at=NOW
    )

    by_code = {
        (
            finding.code,
            finding.component,
        ):
            finding
        for finding in snapshot.diagnostics
    }

    degraded = by_code[
        (
            "M14_RUNTIME_COMPONENT_DEGRADED",
            "MARKET_DATA",
        )
    ]

    assert (
        degraded.severity
        is DiagnosticSeverity.WARNING
    )

    failed = by_code[
        (
            "M14_RUNTIME_COMPONENT_FAILED",
            "EXECUTION",
        )
    ]

    assert (
        failed.severity
        is DiagnosticSeverity.CRITICAL
    )


def test_capture_reports_missing_runtime_health() -> None:
    service = ObservabilityService(
        runtime_health=FakeHealthReader(
            None
        )
    )

    snapshot = service.capture(
        captured_at=NOW
    )

    assert snapshot.runtime_health is None
    assert snapshot.metrics == ()

    assert len(
        snapshot.diagnostics
    ) == 1

    assert (
        snapshot.diagnostics[0].code
        == "M14_RUNTIME_HEALTH_UNAVAILABLE"
    )


def test_capture_combines_optional_sources() -> None:
    service = ObservabilityService(
        runtime_health=FakeHealthReader(
            make_health_snapshot()
        ),
        metric_sources=(
            FakeMetricSource(),
        ),
        diagnostic_sources=(
            FakeDiagnosticSource(),
        ),
    )

    snapshot = service.capture(
        captured_at=NOW
    )

    assert any(
        metric.name
        == "phoenix.custom.metric"
        for metric
        in snapshot.metrics
    )

    assert any(
        finding.code
        == "CUSTOM_DIAGNOSTIC"
        for finding
        in snapshot.diagnostics
    )


def test_capture_does_not_require_health_evaluation() -> None:
    """
    The M14 contract reads latest_snapshot only.

    A FakeHealthReader intentionally exposes no evaluate() method.
    """

    service = ObservabilityService(
        runtime_health=FakeHealthReader(
            make_health_snapshot()
        )
    )

    snapshot = service.capture(
        captured_at=NOW
    )

    assert snapshot.runtime_health is not None
