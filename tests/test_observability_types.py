from datetime import datetime

import pytest

from src.observability.observability_types import (
    DiagnosticFinding,
    DiagnosticSeverity,
    MetricSample,
    MetricType,
)


NOW = datetime(
    2026,
    8,
    30,
    10,
    30,
)


def test_metric_sample_accepts_valid_gauge() -> None:
    sample = MetricSample(
        name="phoenix.test.gauge",
        metric_type=MetricType.GAUGE,
        value=3.5,
        captured_at=NOW,
        labels=(
            (
                "component",
                "runtime",
            ),
        ),
    )

    assert sample.value == 3.5


def test_metric_sample_rejects_negative_counter() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        MetricSample(
            name="phoenix.test.counter",
            metric_type=MetricType.COUNTER,
            value=-1.0,
            captured_at=NOW,
        )


def test_metric_sample_rejects_duplicate_labels() -> None:
    with pytest.raises(
        ValueError,
        match="unique",
    ):
        MetricSample(
            name="phoenix.test.gauge",
            metric_type=MetricType.GAUGE,
            value=1.0,
            captured_at=NOW,
            labels=(
                (
                    "component",
                    "runtime",
                ),
                (
                    "component",
                    "database",
                ),
            ),
        )


def test_diagnostic_finding_normalizes_text() -> None:
    finding = DiagnosticFinding(
        code="  TEST_CODE  ",
        severity=DiagnosticSeverity.INFO,
        message="  diagnostic message  ",
        component="  runtime  ",
    )

    assert finding.code == "TEST_CODE"
    assert finding.message == "diagnostic message"
    assert finding.component == "runtime"
