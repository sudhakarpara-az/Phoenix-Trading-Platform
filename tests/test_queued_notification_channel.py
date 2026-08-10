"""
M11 asynchronous notification delivery tests.
"""

from __future__ import annotations

from datetime import datetime
from threading import Event

from src.notifications.notification_types import (
    NotificationCategory,
    NotificationDeliveryResult,
    NotificationMessage,
    NotificationSeverity,
)
from src.notifications.queued_channel import (
    QueuedNotificationChannel,
)
from src.runtime.runtime_events import (
    RuntimeEventType,
)
from src.runtime.runtime_types import (
    RuntimeId,
)


NOW = datetime(
    2026,
    8,
    10,
    15,
    5,
)


def message(
    value: str = "E-1",
) -> NotificationMessage:
    return NotificationMessage(
        notification_id=(
            f"NOTIFY:{value}"
        ),
        runtime_id=RuntimeId(
            "PHOENIX:2026-08-10:M11"
        ),
        source_event_id=value,
        event_type=(
            RuntimeEventType
            .ENTRY_ORDER_FILLED
        ),
        severity=(
            NotificationSeverity.INFO
        ),
        category=(
            NotificationCategory.TRADE
        ),
        title="Entry filled",
        body="Position opened.",
        occurred_at=NOW,
    )


class RecordingChannel:
    def __init__(
        self,
    ) -> None:
        self.received: list[
            NotificationMessage
        ] = []

        self.received_event = Event()

    @property
    def name(
        self,
    ) -> str:
        return "RECORDING"

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        self.received.append(
            message
        )

        self.received_event.set()

        return NotificationDeliveryResult(
            channel=self.name,
            success=True,
            attempted_at=NOW,
        )


class FailingChannel:
    def __init__(
        self,
    ) -> None:
        self.calls = 0
        self.called = Event()

    @property
    def name(
        self,
    ) -> str:
        return "FAILING"

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        del message

        self.calls += 1
        self.called.set()

        return NotificationDeliveryResult(
            channel=self.name,
            success=False,
            attempted_at=NOW,
            error="offline",
        )


def test_send_before_start_only_queues():
    downstream = RecordingChannel()

    queued = QueuedNotificationChannel(
        downstream=downstream
    )

    result = queued.send(
        message()
    )

    assert result.success is True
    assert queued.pending_count == 1

    # Critical non-blocking proof:
    # send() did not call downstream.
    assert downstream.received == []

    queued.start()

    assert downstream.received_event.wait(
        timeout=1
    )

    queued.stop()

    assert len(
        downstream.received
    ) == 1

    assert queued.delivered_count == 1


def test_downstream_failure_is_isolated():
    downstream = FailingChannel()

    queued = QueuedNotificationChannel(
        downstream=downstream
    )

    queued.start()

    result = queued.send(
        message()
    )

    assert result.success is True

    assert downstream.called.wait(
        timeout=1
    )

    queued.stop()

    assert downstream.calls == 1

    assert (
        queued.failed_delivery_count
        == 1
    )


def test_queue_start_stop_are_idempotent():
    queued = QueuedNotificationChannel(
        downstream=RecordingChannel()
    )

    queued.start()
    queued.start()

    assert queued.started is True

    queued.stop()
    queued.stop()

    assert queued.started is False


def test_stopped_queue_rejects_new_message():
    queued = QueuedNotificationChannel(
        downstream=RecordingChannel()
    )

    queued.start()
    queued.stop()

    result = queued.send(
        message()
    )

    assert result.success is False

    assert result.error is not None

    assert (
        "not accepting"
        in result.error
    )


def test_bounded_queue_drops_without_blocking():
    queued = QueuedNotificationChannel(
        downstream=RecordingChannel(),
        capacity=1,
    )

    first = queued.send(
        message(
            "E-1"
        )
    )

    second = queued.send(
        message(
            "E-2"
        )
    )

    assert first.success is True
    assert second.success is False

    assert queued.pending_count == 1
    assert queued.dropped_count == 1

def test_queue_snapshot_exposes_operational_counters():
    queued = QueuedNotificationChannel(
        downstream=RecordingChannel(),
        capacity=3,
    )

    queued.send(
        message(
            "SNAPSHOT-1"
        )
    )

    snapshot = queued.snapshot(
        captured_at=NOW
    )

    assert snapshot.started is False
    assert snapshot.accepting is True

    assert snapshot.capacity == 3
    assert snapshot.pending_count == 1

    assert snapshot.delivered_count == 0
    assert snapshot.failed_delivery_count == 0
    assert snapshot.dropped_count == 0

    assert snapshot.lifecycle_failure_count == 0
    assert snapshot.last_lifecycle_error is None

    assert snapshot.captured_at == NOW
