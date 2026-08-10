"""
M11 fail-isolated notification dispatcher tests.
"""

from datetime import datetime

from src.notifications.notification_dispatcher import (
    NotificationDispatcher,
)
from src.notifications.notification_types import (
    NotificationCategory,
    NotificationDeliveryResult,
    NotificationMessage,
    NotificationSeverity,
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
    14,
    40,
)


def message() -> NotificationMessage:
    return NotificationMessage(
        notification_id="NOTIFY:EVENT-001",
        runtime_id=RuntimeId(
            "PHOENIX:2026-08-10:M11"
        ),
        source_event_id="EVENT-001",
        event_type=(
            RuntimeEventType
            .ENTRY_ORDER_FAILED
        ),
        severity=(
            NotificationSeverity.ERROR
        ),
        category=(
            NotificationCategory.TRADE
        ),
        title="Entry order failed",
        body="Order processing failed.",
        occurred_at=NOW,
    )


class RecordingChannel:
    def __init__(
        self,
        name: str = "RECORDING",
    ) -> None:
        self._name = name
        self.messages: list[
            NotificationMessage
        ] = []

    @property
    def name(
        self,
    ) -> str:
        return self._name

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


class ExplodingChannel:
    @property
    def name(
        self,
    ) -> str:
        return "EXPLODING"

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        del message

        raise RuntimeError(
            "transport unavailable"
        )


class InvalidResultChannel:
    @property
    def name(
        self,
    ) -> str:
        return "INVALID"

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        del message

        return "not-a-result"  # type: ignore[return-value]


def test_dispatches_to_all_channels():
    first = RecordingChannel(
        "FIRST"
    )

    second = RecordingChannel(
        "SECOND"
    )

    dispatcher = NotificationDispatcher(
        channels=(
            first,
            second,
        )
    )

    item = message()

    result = dispatcher.dispatch(
        item,
        dispatched_at=NOW,
    )

    assert first.messages == [
        item
    ]

    assert second.messages == [
        item
    ]

    assert result.channel_count == 2
    assert result.successful_count == 2
    assert result.failed_count == 0
    assert result.successful is True


def test_one_channel_exception_does_not_block_next_channel():
    healthy = RecordingChannel(
        "HEALTHY"
    )

    dispatcher = NotificationDispatcher(
        channels=(
            ExplodingChannel(),
            healthy,
        )
    )

    item = message()

    result = dispatcher.dispatch(
        item,
        dispatched_at=NOW,
    )

    assert healthy.messages == [
        item
    ]

    assert result.channel_count == 2
    assert result.successful_count == 1
    assert result.failed_count == 1

    failed = result.deliveries[0]

    assert failed.channel == "EXPLODING"
    assert failed.success is False

    assert failed.error is not None

    assert (
        "transport unavailable"
        in failed.error
    )


def test_invalid_channel_result_is_isolated():
    dispatcher = NotificationDispatcher(
        channels=(
            InvalidResultChannel(),
        )
    )

    result = dispatcher.dispatch(
        message(),
        dispatched_at=NOW,
    )

    assert result.channel_count == 1
    assert result.failed_count == 1
    assert result.deliveries[0].success is False


def test_zero_channels_is_valid_noop():
    dispatcher = NotificationDispatcher()

    result = dispatcher.dispatch(
        message(),
        dispatched_at=NOW,
    )

    assert result.channel_count == 0
    assert result.failed_count == 0
    assert result.successful is True
