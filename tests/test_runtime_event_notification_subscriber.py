"""
M11 RuntimeEvent notification bridge tests.
"""

from datetime import datetime

from src.notifications.notification_dispatcher import (
    NotificationDispatcher,
)
from src.notifications.notification_types import (
    NotificationDeliveryResult,
    NotificationMessage,
    NotificationSeverity,
)
from src.notifications.runtime_event_subscriber import (
    RuntimeEventNotificationSubscriber,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.runtime_events import (
    RuntimeEvent,
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
    50,
)

RUNTIME_ID = RuntimeId(
    "PHOENIX:2026-08-10:M11"
)


def event(
    event_type: RuntimeEventType,
    *,
    event_id: str = "EVENT-001",
    payload=None,
) -> RuntimeEvent:
    return RuntimeEvent(
        event_id=event_id,
        runtime_id=RUNTIME_ID,
        event_type=event_type,
        occurred_at=NOW,
        payload=payload,
        correlation_id="TRADE-001",
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
            "Telegram unavailable"
        )


def test_subscriber_uses_selected_operational_events_only():
    bus = RuntimeEventBus()

    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=(
                NotificationDispatcher()
            )
        )
    )

    added = subscriber.subscribe(
        bus
    )

    assert added

    assert (
        bus.subscriber_count(
            RuntimeEventType
            .ENTRY_ORDER_FILLED
        )
        == 1
    )

    assert (
        bus.subscriber_count(
            RuntimeEventType
            .RECOVERY_FAILED
        )
        == 1
    )

    assert (
        bus.subscriber_count(
            RuntimeEventType.MARKET_TICK
        )
        == 0
    )

    assert (
        bus.subscriber_count(
            RuntimeEventType.PNL_UPDATED
        )
        == 0
    )

    assert (
        bus.subscriber_count(
            RuntimeEventType.RISK_UPDATED
        )
        == 0
    )


def test_subscribe_is_idempotent():
    bus = RuntimeEventBus()

    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=(
                NotificationDispatcher()
            )
        )
    )

    first = subscriber.subscribe(
        bus
    )

    second = subscriber.subscribe(
        bus
    )

    assert first
    assert second == ()

    assert (
        bus.subscriber_count(
            RuntimeEventType.RUNTIME_FAILED
        )
        == 1
    )


def test_runtime_failed_maps_to_critical_notification():
    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=(
                NotificationDispatcher()
            )
        )
    )

    message = subscriber.message_for(
        event(
            RuntimeEventType.RUNTIME_FAILED,
            payload="database unavailable",
        )
    )

    assert message is not None

    assert (
        message.severity
        is NotificationSeverity.CRITICAL
    )

    assert (
        message.notification_id
        == "NOTIFY:EVENT-001"
    )

    assert (
        message.source_event_id
        == "EVENT-001"
    )

    assert (
        "database unavailable"
        in message.body
    )


def test_market_tick_has_no_notification_message():
    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=(
                NotificationDispatcher()
            )
        )
    )

    assert (
        subscriber.message_for(
            event(
                RuntimeEventType.MARKET_TICK
            )
        )
        is None
    )


def test_published_event_reaches_channel():
    channel = RecordingChannel()

    dispatcher = NotificationDispatcher(
        channels=(
            channel,
        )
    )

    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=dispatcher
        )
    )

    bus = RuntimeEventBus()

    subscriber.subscribe(
        bus
    )

    runtime_event = event(
        RuntimeEventType
        .ENTRY_ORDER_FILLED
    )

    result = bus.publish(
        runtime_event
    )

    assert result.successful is True

    assert len(
        channel.messages
    ) == 1

    message = channel.messages[0]

    assert (
        message.event_type
        is RuntimeEventType
        .ENTRY_ORDER_FILLED
    )

    assert (
        message.source_event_id
        == runtime_event.event_id
    )


def test_channel_exception_never_fails_runtime_event_bus():
    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=(
                NotificationDispatcher(
                    channels=(
                        ExplodingChannel(),
                    )
                )
            )
        )
    )

    bus = RuntimeEventBus()

    subscriber.subscribe(
        bus
    )

    result = bus.publish(
        event(
            RuntimeEventType
            .EXIT_ORDER_FAILED
        )
    )

    # Core M11 invariant:
    # notification transport failure must not turn a valid
    # Phoenix event publication into RuntimeEventDispatchError.
    assert result.subscriber_count == 1
    assert result.delivered_count == 1
    assert result.failed_count == 0
    assert result.successful is True


def test_unmapped_event_does_not_reach_channel():
    channel = RecordingChannel()

    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=(
                NotificationDispatcher(
                    channels=(
                        channel,
                    )
                )
            )
        )
    )

    bus = RuntimeEventBus()

    subscriber.subscribe(
        bus
    )

    result = bus.publish(
        event(
            RuntimeEventType.PNL_UPDATED
        )
    )

    assert result.subscriber_count == 0

    assert channel.messages == []

def test_runtime_event_payload_is_safely_enriched():
    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=(
                NotificationDispatcher()
            )
        )
    )

    message = subscriber.message_for(
        event(
            RuntimeEventType
            .POSITION_OPENED,
            payload={
                "entity_type": "POSITION",
                "entity_id": "POS-001",
                "token": "SHOULD-NOT-LEAK",
            },
        )
    )

    assert message is not None

    assert (
        "Entity: POSITION"
        in message.body
    )

    assert (
        "ID: POS-001"
        in message.body
    )

    assert (
        "SHOULD-NOT-LEAK"
        not in message.body
    )


def test_same_runtime_event_id_is_dispatched_once():
    channel = RecordingChannel()

    subscriber = (
        RuntimeEventNotificationSubscriber(
            dispatcher=(
                NotificationDispatcher(
                    channels=(
                        channel,
                    )
                )
            )
        )
    )

    runtime_event = event(
        RuntimeEventType
        .ENTRY_ORDER_FILLED,
        event_id="EVENT-DUPLICATE",
    )

    subscriber.handle(
        runtime_event
    )

    subscriber.handle(
        runtime_event
    )

    assert len(
        channel.messages
    ) == 1

    assert subscriber.duplicate_count == 1
