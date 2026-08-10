from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pytest

from src.notifications.daily_summary import (
    DailyOperationalSummaryCollector,
)
from src.notifications.end_of_day_notifications import (
    DailyOperationalSummaryDispatchService,
    TradingDayEndOfDayEvaluator,
    TradingDayEndOfDayNotificationCoordinator,
)
from src.notifications.notification_dispatcher import (
    NotificationDispatcher,
)
from src.notifications.notification_types import (
    NotificationCategory,
    NotificationDeliveryResult,
    NotificationMessage,
)
from src.notifications.queued_channel import (
    QueuedNotificationChannel,
)
from src.runtime.runtime_types import (
    RuntimeId,
)
from src.services.scheduler import (
    TradingDayEndOfDayError,
    TradingDayEndOfDayResult,
)


NOW = datetime(
    2026,
    8,
    10,
    15,
    20,
)

RUNTIME_ID = RuntimeId(
    "PHOENIX:2026-08-10:M11"
)


class RecordingChannel:
    def __init__(
        self,
    ) -> None:
        self.messages: list[
            NotificationMessage
        ] = []

    @property
    def name(
        self,
    ) -> str:
        return "RECORDING"

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        self.messages.append(
            message
        )

        return NotificationDeliveryResult(
            channel=self.name,
            success=True,
            attempted_at=NOW,
        )


class FailOnceChannel:
    def __init__(
        self,
    ) -> None:
        self.calls = 0

    @property
    def name(
        self,
    ) -> str:
        return "FAIL_ONCE"

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        del message

        self.calls += 1

        if self.calls == 1:
            return NotificationDeliveryResult(
                channel=self.name,
                success=False,
                attempted_at=NOW,
                error="queue full",
            )

        return NotificationDeliveryResult(
            channel=self.name,
            success=True,
            attempted_at=NOW,
        )


class FakeEndOfDay:
    def __init__(
        self,
        *,
        complete: bool,
        error: Exception | None = None,
    ) -> None:
        self._complete = complete
        self._error = error
        self.calls = 0

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayEndOfDayResult:
        del evaluated_at

        self.calls += 1

        if self._error is not None:
            raise self._error

        return cast(
            TradingDayEndOfDayResult,
            SimpleNamespace(
                complete=self._complete
            ),
        )


def make_summary_service(
    channel,
) -> tuple[
    DailyOperationalSummaryCollector,
    DailyOperationalSummaryDispatchService,
]:
    collector = (
        DailyOperationalSummaryCollector(
            runtime_id=RUNTIME_ID
        )
    )

    dispatcher = NotificationDispatcher(
        channels=(
            channel,
        )
    )

    service = (
        DailyOperationalSummaryDispatchService(
            collector=collector,
            dispatcher=dispatcher,
            enabled=True,
        )
    )

    return (
        collector,
        service,
    )


def test_incomplete_eod_does_not_dispatch_summary():
    channel = RecordingChannel()

    (
        _,
        service,
    ) = make_summary_service(
        channel
    )

    coordinator = (
        TradingDayEndOfDayNotificationCoordinator(
            runtime_id=RUNTIME_ID,
            end_of_day=cast(
                TradingDayEndOfDayEvaluator,
                FakeEndOfDay(
                    complete=False
                ),
            ),
            summary_service=service,
            alert_dispatcher=(
                NotificationDispatcher()
            ),
        )
    )

    result = coordinator.evaluate(
        evaluated_at=NOW
    )

    assert result.summary_result is None

    assert channel.messages == []


def test_complete_eod_dispatches_summary_once():
    channel = RecordingChannel()

    (
        _,
        service,
    ) = make_summary_service(
        channel
    )

    eod = FakeEndOfDay(
        complete=True
    )

    coordinator = (
        TradingDayEndOfDayNotificationCoordinator(
            runtime_id=RUNTIME_ID,
            end_of_day=cast(
                TradingDayEndOfDayEvaluator,
                eod,
            ),
            summary_service=service,
            alert_dispatcher=(
                NotificationDispatcher()
            ),
        )
    )

    first = coordinator.evaluate(
        evaluated_at=NOW
    )

    second = coordinator.evaluate(
        evaluated_at=NOW
    )

    assert first.summary_result is not None
    assert first.summary_result.attempted is True
    assert first.summary_result.successful is True

    assert second.summary_result is not None

    assert (
        second.summary_result.already_dispatched
        is True
    )

    assert len(
        channel.messages
    ) == 1

    assert (
        channel.messages[0].category
        is NotificationCategory.SUMMARY
    )


def test_failed_summary_delivery_remains_retryable():
    channel = FailOnceChannel()

    (
        _,
        service,
    ) = make_summary_service(
        channel
    )

    first = service.dispatch(
        generated_at=NOW
    )

    second = service.dispatch(
        generated_at=NOW
    )

    assert first.attempted is True
    assert first.successful is False

    assert second.attempted is True
    assert second.successful is True

    assert channel.calls == 2


def test_eod_failure_alerts_then_reraises_original_error():
    recording = RecordingChannel()

    collector = (
        DailyOperationalSummaryCollector(
            runtime_id=RUNTIME_ID
        )
    )

    alert_dispatcher = NotificationDispatcher(
        channels=(
            collector,
            recording,
        )
    )

    summary_service = (
        DailyOperationalSummaryDispatchService(
            collector=collector,
            dispatcher=NotificationDispatcher(),
            enabled=False,
        )
    )

    original = TradingDayEndOfDayError(
        "close readiness unavailable"
    )

    coordinator = (
        TradingDayEndOfDayNotificationCoordinator(
            runtime_id=RUNTIME_ID,
            end_of_day=cast(
                TradingDayEndOfDayEvaluator,
                FakeEndOfDay(
                    complete=False,
                    error=original,
                ),
            ),
            summary_service=summary_service,
            alert_dispatcher=(
                alert_dispatcher
            ),
        )
    )

    with pytest.raises(
        TradingDayEndOfDayError,
        match="close readiness unavailable",
    ):
        coordinator.evaluate(
            evaluated_at=NOW
        )

    assert len(
        recording.messages
    ) == 1

    alert = recording.messages[0]

    assert (
        alert.category
        is NotificationCategory.RUNTIME
    )

    assert (
        alert.event_type
        is None
    )

    assert (
        "Trading-day close evaluation failed"
        == alert.title
    )

    snapshot = collector.snapshot(
        captured_at=NOW
    )

    assert snapshot.error_count == 1
    assert snapshot.runtime_count == 1


def test_summary_contains_queue_observability():
    downstream = RecordingChannel()

    queue = QueuedNotificationChannel(
        downstream=downstream,
        capacity=4,
    )

    collector = (
        DailyOperationalSummaryCollector(
            runtime_id=RUNTIME_ID
        )
    )

    recording = RecordingChannel()

    service = (
        DailyOperationalSummaryDispatchService(
            collector=collector,
            dispatcher=(
                NotificationDispatcher(
                    channels=(
                        recording,
                    )
                )
            ),
            queued_channel=queue,
            enabled=True,
        )
    )

    result = service.dispatch(
        generated_at=NOW
    )

    assert result.successful is True

    assert len(
        recording.messages
    ) == 1

    body = recording.messages[0].body

    assert (
        "Delivery queue ? "
        in body
    )

    assert (
        "pending 0"
        in body
    )

    assert (
        "dropped 0"
        in body
    )
