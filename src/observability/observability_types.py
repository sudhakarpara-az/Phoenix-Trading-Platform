"""
Phoenix M14 transport-neutral observability read models.

These models describe already-observed operational facts. They do
not perform health checks, mutate runtime state, repair components,
or own subsystem lifecycle policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class MetricType(
    str,
    Enum,
):
    """
    Semantics of one point-in-time metric sample.
    """

    COUNTER = "COUNTER"
    GAUGE = "GAUGE"


@dataclass(
    frozen=True,
    slots=True,
)
class MetricSample:
    """
    One immutable metric observation.

    COUNTER values are required to be non-negative. M14 currently
    stores no historical time series; consumers receive point-in-time
    samples only.
    """

    name: str
    metric_type: MetricType
    value: float
    captured_at: datetime
    labels: tuple[
        tuple[str, str],
        ...
    ] = ()

    def __post_init__(
        self,
    ) -> None:
        name = self.name.strip()

        if not name:
            raise ValueError(
                "metric name cannot be empty"
            )

        if name != self.name:
            object.__setattr__(
                self,
                "name",
                name,
            )

        if not isfinite(self.value):
            raise ValueError(
                "metric value must be finite"
            )

        if (
            self.metric_type
            is MetricType.COUNTER
            and self.value < 0
        ):
            raise ValueError(
                "counter metric cannot be negative"
            )

        seen: set[str] = set()

        for key, value in self.labels:
            normalized_key = key.strip()
            normalized_value = value.strip()

            if not normalized_key:
                raise ValueError(
                    "metric label key cannot be empty"
                )

            if not normalized_value:
                raise ValueError(
                    "metric label value cannot be empty"
                )

            if normalized_key in seen:
                raise ValueError(
                    "metric label keys must be unique"
                )

            seen.add(
                normalized_key
            )

            if (
                normalized_key != key
                or normalized_value != value
            ):
                raise ValueError(
                    "metric labels must already be normalized"
                )


class DiagnosticSeverity(
    str,
    Enum,
):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(
    frozen=True,
    slots=True,
)
class DiagnosticFinding:
    """
    One immutable operational diagnostic.

    A finding reports an observed condition only. It never performs
    component repair or alters trading state.
    """

    code: str
    severity: DiagnosticSeverity
    message: str
    component: str | None = None

    def __post_init__(
        self,
    ) -> None:
        code = self.code.strip()
        message = self.message.strip()

        if not code:
            raise ValueError(
                "diagnostic code cannot be empty"
            )

        if not message:
            raise ValueError(
                "diagnostic message cannot be empty"
            )

        if code != self.code:
            object.__setattr__(
                self,
                "code",
                code,
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
                    "diagnostic component cannot be empty"
                )

            if component != self.component:
                object.__setattr__(
                    self,
                    "component",
                    component,
                )


@dataclass(
    frozen=True,
    slots=True,
)
class ComponentHealthView:
    """
    Passive projection of one M08 component-health result.
    """

    component: str
    status: str
    checked_at: datetime
    critical: bool
    message: str | None


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeHealthView:
    """
    Passive projection of the latest retained M08 health snapshot.
    """

    status: str
    checked_at: datetime
    components: tuple[
        ComponentHealthView,
        ...
    ]


@dataclass(
    frozen=True,
    slots=True,
)
class ObservabilitySnapshot:
    """
    Coherent M14 point-in-time observability result.

    No historical metric or diagnostic retention is implied.
    """

    captured_at: datetime

    runtime_health: (
        RuntimeHealthView
        | None
    )

    metrics: tuple[
        MetricSample,
        ...
    ]

    diagnostics: tuple[
        DiagnosticFinding,
        ...
    ]


__all__ = [
    "ComponentHealthView",
    "DiagnosticFinding",
    "DiagnosticSeverity",
    "MetricSample",
    "MetricType",
    "ObservabilitySnapshot",
    "RuntimeHealthView",
]
