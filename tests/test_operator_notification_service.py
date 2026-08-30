from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pytest

from src.api.operator_notifications import (
    OperatorNotificationService,
)
from src.notifications.daily_summary import (
    DailyOperationalSummarySnapshot,
)
from src.notifications.queued_channel import (
    NotificationQueueSnapshot,
)


CAPTURED_AT = datetime(
    2026,
    8,
    31,
    11,
    30,
)


class FakeSummaryCollector:
    def __init__(
        self,
    ) -> None:
        self.calls: list[
            datetime
        ] = []

    def snapshot(
        self,
        *,
        captured_at: datetime,
    ) -> DailyOperationalSummarySnapshot:
        self.calls.append(
            captured_at
        )

        return cast(
            DailyOperationalSummarySnapshot,
            SimpleNamespace(
                runtime_id=SimpleNamespace(
                    value="RUNTIME-1"
                ),
                total_count=12,
                info_count=5,
                warning_count=3,
                error_count=2,
                critical_count=2,
                runtime_count=2,
                trade_count=3,
                risk_count=2,
                recovery_count=1,
                health_count=3,
                summary_count=1,
                first_event_at=datetime(
                    2026,
                    8,
                    31,
                    9,
                    20,
                ),
                last_event_at=datetime(
                    2026,
                    8,
                    31,
                    11,
                    25,
                ),
                captured_at=captured_at,
            ),
        )


class FakeQueue:
    def __init__(
        self,
    ) -> None:
        self.calls: list[
            datetime
        ] = []

    def snapshot(
        self,
        *,
        captured_at: datetime,
    ) -> NotificationQueueSnapshot:
        self.calls.append(
            captured_at
        )

        return cast(
            NotificationQueueSnapshot,
            SimpleNamespace(
                started=True,
                accepting=True,
                capacity=256,
                pending_count=4,
                delivered_count=100,
                failed_delivery_count=3,
                dropped_count=2,
                lifecycle_failure_count=1,
                last_lifecycle_error=(
                    "worker restart"
                ),
                captured_at=captured_at,
            ),
        )


def test_capture_maps_exact_m11_snapshots() -> None:
    summary = FakeSummaryCollector()
    queue = FakeQueue()

    service = OperatorNotificationService(
        summary_collector=summary,
        queued_channel=queue,
    )

    result = service.capture(
        captured_at=CAPTURED_AT,
    )

    assert (
        service.summary_collector
        is summary
    )

    assert (
        service.queued_channel
        is queue
    )

    assert summary.calls == [
        CAPTURED_AT,
    ]

    assert queue.calls == [
        CAPTURED_AT,
    ]

    assert (
        result.summary.runtime_id
        == "RUNTIME-1"
    )

    assert result.summary.total_count == 12
    assert result.summary.info_count == 5
    assert result.summary.warning_count == 3
    assert result.summary.error_count == 2
    assert result.summary.critical_count == 2

    assert result.summary.runtime_count == 2
    assert result.summary.trade_count == 3
    assert result.summary.risk_count == 2
    assert result.summary.recovery_count == 1
    assert result.summary.health_count == 3
    assert result.summary.summary_count == 1

    assert result.queue is not None

    assert result.queue.started is True
    assert result.queue.accepting is True
    assert result.queue.capacity == 256
    assert result.queue.pending_count == 4
    assert result.queue.delivered_count == 100
    assert (
        result.queue.failed_delivery_count
        == 3
    )
    assert result.queue.dropped_count == 2
    assert (
        result.queue.lifecycle_failure_count
        == 1
    )
    assert (
        result.queue.last_lifecycle_error
        == "worker restart"
    )

    assert result.captured_at is CAPTURED_AT


def test_capture_supports_no_queue() -> None:
    summary = FakeSummaryCollector()

    service = OperatorNotificationService(
        summary_collector=summary,
        queued_channel=None,
    )

    result = service.capture(
        captured_at=CAPTURED_AT,
    )

    assert result.queue is None

    assert summary.calls == [
        CAPTURED_AT,
    ]


def test_capture_rejects_non_datetime() -> None:
    service = OperatorNotificationService(
        summary_collector=(
            FakeSummaryCollector()
        ),
        queued_channel=None,
    )

    with pytest.raises(
        TypeError,
        match="captured_at must be datetime",
    ):
        service.capture(
            captured_at=object(),  # type: ignore[arg-type]
        )
