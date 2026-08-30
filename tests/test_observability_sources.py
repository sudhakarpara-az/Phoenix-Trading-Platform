from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, cast

from src.notifications.queued_channel import (
    NotificationQueueSnapshot,
)
from src.observability.observability_sources import (
    AccountHealthObservabilitySource,
    NotificationQueueObservabilitySource,
    RuntimeEventBusObservabilitySource,
    SchedulerObservabilitySource,
)
from src.observability.observability_types import (
    DiagnosticSeverity,
)
from src.runtime.event_bus import RuntimeEventBus
from src.runtime.runtime_events import RuntimeEventType
from src.services.scheduler import TradingDayScheduler


NOW = datetime(
    2026,
    8,
    31,
    10,
    0,
)


class FakeAccountHealthRepository:
    def __init__(
        self,
        record: Any,
    ) -> None:
        self.record = record

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> Any:
        assert broker == "DHAN"
        assert account_id == "TEST-ACCOUNT"
        return self.record


class FakeQueue:
    def __init__(
        self,
        snapshot: NotificationQueueSnapshot,
    ) -> None:
        self._snapshot = snapshot

    def snapshot(
        self,
        *,
        captured_at: datetime,
    ) -> NotificationQueueSnapshot:
        assert captured_at == NOW
        return self._snapshot


def test_account_health_source_projects_healthy_record() -> None:
    record = SimpleNamespace(
        status="HEALTHY",
        broker_connected=True,
        session_authenticated=True,
        profile_available=True,
        funds_available=True,
        message=None,
    )

    repository = FakeAccountHealthRepository(
        record
    )

    source = AccountHealthObservabilitySource(
        repository=cast(
            Any,
            repository,
        ),
        broker="DHAN",
        account_id="TEST-ACCOUNT",
    )

    metrics = {
        metric.name: metric.value
        for metric in source.collect_metrics(
            captured_at=NOW
        )
    }

    assert (
        metrics[
            "phoenix.account.health.ready"
        ]
        == 1.0
    )

    assert (
        metrics[
            "phoenix.account.health.broker_connected"
        ]
        == 1.0
    )

    assert (
        source.collect_diagnostics(
            captured_at=NOW
        )
        == ()
    )


def test_account_health_source_reports_unhealthy_record() -> None:
    record = SimpleNamespace(
        status="UNHEALTHY",
        broker_connected=False,
        session_authenticated=False,
        profile_available=False,
        funds_available=False,
        message="broker unavailable",
    )

    source = AccountHealthObservabilitySource(
        repository=cast(
            Any,
            FakeAccountHealthRepository(
                record
            ),
        ),
        broker="DHAN",
        account_id="TEST-ACCOUNT",
    )

    findings = (
        source.collect_diagnostics(
            captured_at=NOW
        )
    )

    assert len(findings) == 1

    assert (
        findings[0].code
        == "M14_ACCOUNT_HEALTH_NOT_HEALTHY"
    )

    assert (
        findings[0].severity
        is DiagnosticSeverity.ERROR
    )

    assert (
        findings[0].message
        == "broker unavailable"
    )


def test_account_health_source_reports_missing_record() -> None:
    source = AccountHealthObservabilitySource(
        repository=cast(
            Any,
            FakeAccountHealthRepository(
                None
            ),
        ),
        broker="DHAN",
        account_id="TEST-ACCOUNT",
    )

    assert (
        source.collect_metrics(
            captured_at=NOW
        )
        == ()
    )

    findings = (
        source.collect_diagnostics(
            captured_at=NOW
        )
    )

    assert len(findings) == 1

    assert (
        findings[0].code
        == "M14_ACCOUNT_HEALTH_UNAVAILABLE"
    )


def test_scheduler_source_projects_created_state() -> None:
    scheduler = TradingDayScheduler(
        trading_date=date(
            2026,
            8,
            31,
        ),
        created_at=NOW,
    )

    source = SchedulerObservabilitySource(
        scheduler=scheduler
    )

    metrics = {
        metric.name: metric
        for metric in source.collect_metrics(
            captured_at=NOW
        )
    }

    assert (
        metrics[
            "phoenix.scheduler.state"
        ].labels
        == (
            (
                "state",
                "CREATED",
            ),
        )
    )

    assert (
        metrics[
            "phoenix.scheduler.terminal"
        ].value
        == 0.0
    )

    assert (
        source.collect_diagnostics(
            captured_at=NOW
        )
        == ()
    )


def test_notification_source_projects_queue_health() -> None:
    queue_snapshot = NotificationQueueSnapshot(
        started=True,
        accepting=True,
        capacity=256,
        pending_count=2,
        delivered_count=5,
        failed_delivery_count=1,
        dropped_count=1,
        lifecycle_failure_count=1,
        last_lifecycle_error="worker failed",
        captured_at=NOW,
    )

    source = NotificationQueueObservabilitySource(
        queue=FakeQueue(
            queue_snapshot
        )
    )

    metrics = {
        metric.name: metric.value
        for metric in source.collect_metrics(
            captured_at=NOW
        )
    }

    assert (
        metrics[
            "phoenix.notification.queue.pending"
        ]
        == 2.0
    )

    assert (
        metrics[
            "phoenix.notification.delivered.total"
        ]
        == 5.0
    )

    codes = {
        finding.code
        for finding in source.collect_diagnostics(
            captured_at=NOW
        )
    }

    assert (
        "M14_NOTIFICATION_DELIVERY_FAILURES"
        in codes
    )

    assert (
        "M14_NOTIFICATION_DROPS"
        in codes
    )

    assert (
        "M14_NOTIFICATION_LIFECYCLE_FAILURES"
        in codes
    )


def test_runtime_event_bus_source_projects_subscribers() -> None:
    event_bus = RuntimeEventBus()

    event_type = next(
        iter(RuntimeEventType)
    )

    def handler(
        event: Any,
    ) -> None:
        del event

    assert event_bus.subscribe(
        event_type,
        handler,
    )

    source = RuntimeEventBusObservabilitySource(
        event_bus=event_bus
    )

    metrics = source.collect_metrics(
        captured_at=NOW
    )

    subscriber_metrics = [
        metric
        for metric in metrics
        if (
            metric.name
            == "phoenix.runtime.event_bus.subscribers"
            and metric.labels
            == (
                (
                    "event_type",
                    event_type.value,
                ),
            )
        )
    ]

    assert len(subscriber_metrics) == 1
    assert subscriber_metrics[0].value == 1.0
