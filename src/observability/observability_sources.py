"""
Phoenix M14 passive subsystem observability sources.

These adapters consume authoritative state owned by earlier milestones.
They do not mutate scheduler, account, broker, notification, or runtime state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.database.schema import AccountHealthSnapshotRecord
from src.notifications.queued_channel import NotificationQueueSnapshot
from src.observability.observability_types import (
    DiagnosticFinding,
    DiagnosticSeverity,
    MetricSample,
    MetricType,
)
from src.runtime.runtime_events import RuntimeEventType
from src.services.scheduler import TradingDaySnapshot, TradingDayState


class AccountHealthRecordReader(Protocol):
    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> AccountHealthSnapshotRecord | None:
        ...


class SchedulerSnapshotReader(Protocol):
    @property
    def snapshot(self) -> TradingDaySnapshot:
        ...


class NotificationQueueSnapshotReader(Protocol):
    def snapshot(
        self,
        *,
        captured_at: datetime,
    ) -> NotificationQueueSnapshot:
        ...


class RuntimeEventBusReader(Protocol):
    @property
    def strict(self) -> bool:
        ...

    def subscriber_count(
        self,
        event_type: RuntimeEventType,
    ) -> int:
        ...


class AccountHealthObservabilitySource:
    def __init__(
        self,
        *,
        repository: AccountHealthRecordReader,
        broker: str,
        account_id: str,
    ) -> None:
        broker = broker.strip()
        account_id = account_id.strip()

        if not broker:
            raise ValueError("broker cannot be empty")

        if not account_id:
            raise ValueError("account_id cannot be empty")

        self._repository = repository
        self._broker = broker
        self._account_id = account_id

    @property
    def repository(self) -> AccountHealthRecordReader:
        return self._repository

    def _latest(
        self,
    ) -> AccountHealthSnapshotRecord | None:
        return self._repository.latest_for_account(
            broker=self._broker,
            account_id=self._account_id,
        )

    def collect_metrics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[MetricSample, ...]:
        record = self._latest()

        if record is None:
            return ()

        labels = (
            ("broker", self._broker),
            ("account_id", self._account_id),
        )

        ready = (
            record.status == "HEALTHY"
            and record.broker_connected
            and record.session_authenticated
            and record.profile_available
            and record.funds_available
        )

        values = (
            ("phoenix.account.health.ready", ready),
            (
                "phoenix.account.health.broker_connected",
                record.broker_connected,
            ),
            (
                "phoenix.account.health.session_authenticated",
                record.session_authenticated,
            ),
            (
                "phoenix.account.health.profile_available",
                record.profile_available,
            ),
            (
                "phoenix.account.health.funds_available",
                record.funds_available,
            ),
        )

        return tuple(
            MetricSample(
                name=name,
                metric_type=MetricType.GAUGE,
                value=1.0 if value else 0.0,
                captured_at=captured_at,
                labels=labels,
            )
            for name, value in values
        )

    def collect_diagnostics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[DiagnosticFinding, ...]:
        del captured_at

        record = self._latest()

        if record is None:
            return (
                DiagnosticFinding(
                    code="M14_ACCOUNT_HEALTH_UNAVAILABLE",
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        "No durable account-health snapshot is available."
                    ),
                    component="ACCOUNT",
                ),
            )

        if record.status == "HEALTHY":
            return ()

        severity = (
            DiagnosticSeverity.ERROR
            if record.status == "UNHEALTHY"
            else DiagnosticSeverity.WARNING
        )

        return (
            DiagnosticFinding(
                code="M14_ACCOUNT_HEALTH_NOT_HEALTHY",
                severity=severity,
                message=(
                    record.message
                    or f"Account health status is {record.status}."
                ),
                component="ACCOUNT",
            ),
        )


class SchedulerObservabilitySource:
    def __init__(
        self,
        *,
        scheduler: SchedulerSnapshotReader,
    ) -> None:
        self._scheduler = scheduler

    @property
    def scheduler(self) -> SchedulerSnapshotReader:
        return self._scheduler

    def collect_metrics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[MetricSample, ...]:
        snapshot = self._scheduler.snapshot

        return (
            MetricSample(
                name="phoenix.scheduler.state",
                metric_type=MetricType.GAUGE,
                value=1.0,
                captured_at=captured_at,
                labels=(("state", snapshot.state.value),),
            ),
            MetricSample(
                name="phoenix.scheduler.accepting_new_entries",
                metric_type=MetricType.GAUGE,
                value=(
                    1.0
                    if snapshot.can_accept_new_entries
                    else 0.0
                ),
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.scheduler.managing_positions",
                metric_type=MetricType.GAUGE,
                value=(
                    1.0
                    if snapshot.can_manage_positions
                    else 0.0
                ),
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.scheduler.terminal",
                metric_type=MetricType.GAUGE,
                value=1.0 if snapshot.is_terminal else 0.0,
                captured_at=captured_at,
            ),
        )

    def collect_diagnostics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[DiagnosticFinding, ...]:
        del captured_at

        snapshot = self._scheduler.snapshot

        if snapshot.state is not TradingDayState.FAILED:
            return ()

        return (
            DiagnosticFinding(
                code="M14_TRADING_DAY_FAILED",
                severity=DiagnosticSeverity.CRITICAL,
                message=(
                    snapshot.failure_message
                    or "Trading day is FAILED."
                ),
                component="SCHEDULER",
            ),
        )


class NotificationQueueObservabilitySource:
    def __init__(
        self,
        *,
        queue: NotificationQueueSnapshotReader,
    ) -> None:
        self._queue = queue

    @property
    def queue(self) -> NotificationQueueSnapshotReader:
        return self._queue

    def collect_metrics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[MetricSample, ...]:
        snapshot = self._queue.snapshot(
            captured_at=captured_at
        )

        return (
            MetricSample(
                name="phoenix.notification.queue.pending",
                metric_type=MetricType.GAUGE,
                value=float(snapshot.pending_count),
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.notification.queue.capacity",
                metric_type=MetricType.GAUGE,
                value=float(snapshot.capacity),
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.notification.queue.started",
                metric_type=MetricType.GAUGE,
                value=1.0 if snapshot.started else 0.0,
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.notification.queue.accepting",
                metric_type=MetricType.GAUGE,
                value=1.0 if snapshot.accepting else 0.0,
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.notification.delivered.total",
                metric_type=MetricType.COUNTER,
                value=float(snapshot.delivered_count),
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.notification.delivery_failed.total",
                metric_type=MetricType.COUNTER,
                value=float(snapshot.failed_delivery_count),
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.notification.dropped.total",
                metric_type=MetricType.COUNTER,
                value=float(snapshot.dropped_count),
                captured_at=captured_at,
            ),
            MetricSample(
                name="phoenix.notification.lifecycle_failed.total",
                metric_type=MetricType.COUNTER,
                value=float(snapshot.lifecycle_failure_count),
                captured_at=captured_at,
            ),
        )

    def collect_diagnostics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[DiagnosticFinding, ...]:
        snapshot = self._queue.snapshot(
            captured_at=captured_at
        )

        findings: list[DiagnosticFinding] = []

        if snapshot.failed_delivery_count > 0:
            findings.append(
                DiagnosticFinding(
                    code="M14_NOTIFICATION_DELIVERY_FAILURES",
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        "Notification delivery failures have occurred."
                    ),
                    component="NOTIFICATIONS",
                )
            )

        if snapshot.dropped_count > 0:
            findings.append(
                DiagnosticFinding(
                    code="M14_NOTIFICATION_DROPS",
                    severity=DiagnosticSeverity.ERROR,
                    message=(
                        "Notifications have been dropped "
                        "by the bounded queue."
                    ),
                    component="NOTIFICATIONS",
                )
            )

        if snapshot.lifecycle_failure_count > 0:
            findings.append(
                DiagnosticFinding(
                    code="M14_NOTIFICATION_LIFECYCLE_FAILURES",
                    severity=DiagnosticSeverity.ERROR,
                    message=(
                        snapshot.last_lifecycle_error
                        or (
                            "Notification queue lifecycle "
                            "failures have occurred."
                        )
                    ),
                    component="NOTIFICATIONS",
                )
            )

        return tuple(findings)


class RuntimeEventBusObservabilitySource:
    """
    RuntimeEventBus currently retains subscriber state only.

    M14 deliberately does not invent publish/failure counters that the
    authoritative event-bus owner does not retain.
    """

    def __init__(
        self,
        *,
        event_bus: RuntimeEventBusReader,
    ) -> None:
        self._event_bus = event_bus

    @property
    def event_bus(self) -> RuntimeEventBusReader:
        return self._event_bus

    def collect_metrics(
        self,
        *,
        captured_at: datetime,
    ) -> tuple[MetricSample, ...]:
        metrics: list[MetricSample] = [
            MetricSample(
                name="phoenix.runtime.event_bus.strict",
                metric_type=MetricType.GAUGE,
                value=1.0 if self._event_bus.strict else 0.0,
                captured_at=captured_at,
            )
        ]

        for event_type in RuntimeEventType:
            metrics.append(
                MetricSample(
                    name="phoenix.runtime.event_bus.subscribers",
                    metric_type=MetricType.GAUGE,
                    value=float(
                        self._event_bus.subscriber_count(
                            event_type
                        )
                    ),
                    captured_at=captured_at,
                    labels=(
                        (
                            "event_type",
                            event_type.value,
                        ),
                    ),
                )
            )

        return tuple(metrics)


__all__ = [
    "AccountHealthObservabilitySource",
    "AccountHealthRecordReader",
    "NotificationQueueObservabilitySource",
    "NotificationQueueSnapshotReader",
    "RuntimeEventBusObservabilitySource",
    "RuntimeEventBusReader",
    "SchedulerObservabilitySource",
    "SchedulerSnapshotReader",
]
