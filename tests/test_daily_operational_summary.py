from datetime import datetime

from src.notifications.daily_summary import (
    DailyOperationalSummaryCollector,
)
from src.notifications.notification_types import (
    NotificationCategory,
    NotificationMessage,
    NotificationSeverity,
)
from src.runtime.runtime_events import (
    RuntimeEventType,
)
from src.runtime.runtime_types import (
    RuntimeId,
)


RUNTIME_ID = RuntimeId(
    "PHOENIX:2026-08-10:M11"
)

NOW = datetime(
    2026,
    8,
    10,
    15,
    20,
)


def message(
    *,
    notification_id: str,
    severity: NotificationSeverity,
    category: NotificationCategory,
) -> NotificationMessage:
    return NotificationMessage(
        notification_id=notification_id,
        runtime_id=RUNTIME_ID,
        source_event_id=(
            notification_id
        ),
        event_type=(
            RuntimeEventType
            .ENTRY_ORDER_FAILED
        ),
        severity=severity,
        category=category,
        title="Operational event",
        body="test",
        occurred_at=NOW,
    )


def test_summary_counts_notifications():
    collector = (
        DailyOperationalSummaryCollector(
            runtime_id=RUNTIME_ID
        )
    )

    collector.send(
        message(
            notification_id="N1",
            severity=(
                NotificationSeverity.INFO
            ),
            category=(
                NotificationCategory.TRADE
            ),
        )
    )

    collector.send(
        message(
            notification_id="N2",
            severity=(
                NotificationSeverity.ERROR
            ),
            category=(
                NotificationCategory.RUNTIME
            ),
        )
    )

    snapshot = collector.snapshot(
        captured_at=NOW
    )

    assert snapshot.total_count == 2
    assert snapshot.info_count == 1
    assert snapshot.error_count == 1
    assert snapshot.trade_count == 1
    assert snapshot.runtime_count == 1


def test_summary_collector_is_idempotent_by_notification_id():
    collector = (
        DailyOperationalSummaryCollector(
            runtime_id=RUNTIME_ID
        )
    )

    item = message(
        notification_id="N1",
        severity=(
            NotificationSeverity.WARNING
        ),
        category=(
            NotificationCategory.HEALTH
        ),
    )

    collector.send(
        item
    )

    collector.send(
        item
    )

    snapshot = collector.snapshot(
        captured_at=NOW
    )

    assert snapshot.total_count == 1
    assert snapshot.warning_count == 1
    assert snapshot.health_count == 1


def test_daily_summary_message_is_synthetic_not_fake_runtime_event():
    collector = (
        DailyOperationalSummaryCollector(
            runtime_id=RUNTIME_ID
        )
    )

    collector.send(
        message(
            notification_id="N1",
            severity=(
                NotificationSeverity.CRITICAL
            ),
            category=(
                NotificationCategory.RECOVERY
            ),
        )
    )

    summary = collector.build_message(
        generated_at=NOW
    )

    assert summary.event_type is None

    assert (
        summary.category
        is NotificationCategory.SUMMARY
    )

    assert (
        summary.severity
        is NotificationSeverity.CRITICAL
    )

    assert (
        "Operational alerts: 1"
        in summary.body
    )
