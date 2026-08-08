"""
Phoenix M08-T05 Runtime Event Bus tests.
"""

from datetime import datetime

import pytest

from src.runtime.event_bus import (
    RuntimeEventBus,
    RuntimeEventDispatchError,
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
    8,
    13,
    0,
)

RUNTIME_ID = RuntimeId(
    "PHOENIX:2026-08-08:TEST"
)


def make_event(
    event_type: RuntimeEventType = (
        RuntimeEventType.SIGNAL_CREATED
    ),
    *,
    payload=None,
    event_id: str = "EVENT-001",
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> RuntimeEvent:
    return RuntimeEvent(
        event_id=event_id,
        runtime_id=RUNTIME_ID,
        event_type=event_type,
        occurred_at=NOW,
        payload=payload,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


# ============================================================
# RuntimeEvent
# ============================================================


def test_runtime_event_creation() -> None:
    event = make_event()

    assert event.event_id == "EVENT-001"

    assert (
        event.event_type
        is RuntimeEventType.SIGNAL_CREATED
    )

    assert event.runtime_id == RUNTIME_ID
    assert event.occurred_at == NOW


def test_runtime_event_preserves_payload() -> None:
    payload = {
        "signal_id": "SIG-001",
        "level": "K5",
    }

    event = make_event(
        payload=payload
    )

    assert event.payload is payload


def test_runtime_event_id_trimmed() -> None:
    event = RuntimeEvent(
        event_id="  EVENT-001  ",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .SIGNAL_CREATED
        ),
        occurred_at=NOW,
    )

    assert event.event_id == "EVENT-001"


def test_empty_runtime_event_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "runtime event id cannot be empty"
        ),
    ):
        RuntimeEvent(
            event_id=" ",
            runtime_id=RUNTIME_ID,
            event_type=(
                RuntimeEventType
                .SIGNAL_CREATED
            ),
            occurred_at=NOW,
        )


def test_correlation_id_supported() -> None:
    event = make_event(
        correlation_id="TRADE-001"
    )

    assert (
        event.correlation_id
        == "TRADE-001"
    )


def test_causation_id_supported() -> None:
    event = make_event(
        causation_id="EVENT-PARENT"
    )

    assert (
        event.causation_id
        == "EVENT-PARENT"
    )


def test_empty_correlation_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "runtime event correlation id "
            "cannot be empty"
        ),
    ):
        make_event(
            correlation_id=" "
        )


def test_empty_causation_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "runtime event causation id "
            "cannot be empty"
        ),
    ):
        make_event(
            causation_id=" "
        )


def test_runtime_event_factory_generates_id() -> None:
    event = RuntimeEvent.create(
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .POSITION_OPENED
        ),
        occurred_at=NOW,
        payload={
            "position_id": "POS-001"
        },
    )

    assert event.event_id

    assert (
        event.event_type
        is RuntimeEventType.POSITION_OPENED
    )


def test_runtime_event_factory_ids_are_unique() -> None:
    first = RuntimeEvent.create(
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .POSITION_OPENED
        ),
        occurred_at=NOW,
    )

    second = RuntimeEvent.create(
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .POSITION_OPENED
        ),
        occurred_at=NOW,
    )

    assert (
        first.event_id
        != second.event_id
    )


# ============================================================
# Subscription
# ============================================================


def test_subscribe_handler() -> None:
    bus = RuntimeEventBus()

    def handler(event):
        del event

    added = bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        handler,
    )

    assert added is True

    assert (
        bus.subscriber_count(
            RuntimeEventType.SIGNAL_CREATED
        )
        == 1
    )


def test_duplicate_subscription_is_blocked() -> None:
    bus = RuntimeEventBus()

    def handler(event):
        del event

    first = bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        handler,
    )

    second = bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        handler,
    )

    assert first is True
    assert second is False

    assert (
        bus.subscriber_count(
            RuntimeEventType.SIGNAL_CREATED
        )
        == 1
    )


def test_non_callable_handler_rejected() -> None:
    bus = RuntimeEventBus()

    with pytest.raises(
        TypeError,
        match=(
            "runtime event handler "
            "must be callable"
        ),
    ):
        bus.subscribe(
            RuntimeEventType.SIGNAL_CREATED,
            "not-callable",
        )


def test_same_handler_can_subscribe_different_events() -> None:
    bus = RuntimeEventBus()

    def handler(event):
        del event

    assert (
        bus.subscribe(
            RuntimeEventType.SIGNAL_CREATED,
            handler,
        )
        is True
    )

    assert (
        bus.subscribe(
            RuntimeEventType.POSITION_OPENED,
            handler,
        )
        is True
    )


def test_subscribers_returns_tuple() -> None:
    bus = RuntimeEventBus()

    def handler(event):
        del event

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        handler,
    )

    subscribers = bus.subscribers(
        RuntimeEventType.SIGNAL_CREATED
    )

    assert subscribers == (
        handler,
    )


# ============================================================
# Unsubscribe
# ============================================================


def test_unsubscribe_handler() -> None:
    bus = RuntimeEventBus()

    def handler(event):
        del event

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        handler,
    )

    removed = bus.unsubscribe(
        RuntimeEventType.SIGNAL_CREATED,
        handler,
    )

    assert removed is True

    assert (
        bus.subscriber_count(
            RuntimeEventType.SIGNAL_CREATED
        )
        == 0
    )


def test_unsubscribe_missing_returns_false() -> None:
    bus = RuntimeEventBus()

    def handler(event):
        del event

    assert (
        bus.unsubscribe(
            RuntimeEventType.SIGNAL_CREATED,
            handler,
        )
        is False
    )


# ============================================================
# Publishing
# ============================================================


def test_publish_to_one_handler() -> None:
    bus = RuntimeEventBus()

    received = []

    def handler(event):
        received.append(
            event
        )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        handler,
    )

    event = make_event()

    result = bus.publish(
        event
    )

    assert received == [
        event
    ]

    assert result.subscriber_count == 1
    assert result.delivered_count == 1
    assert result.failed_count == 0
    assert result.successful is True


def test_publish_to_multiple_handlers() -> None:
    bus = RuntimeEventBus()

    received = []

    def first(event):
        received.append(
            (
                "first",
                event.event_id,
            )
        )

    def second(event):
        received.append(
            (
                "second",
                event.event_id,
            )
        )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        first,
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        second,
    )

    result = bus.publish(
        make_event()
    )

    assert received == [
        (
            "first",
            "EVENT-001",
        ),
        (
            "second",
            "EVENT-001",
        ),
    ]

    assert result.subscriber_count == 2
    assert result.delivered_count == 2


def test_dispatch_order_matches_subscription_order() -> None:
    bus = RuntimeEventBus()

    calls = []

    def first(event):
        del event
        calls.append("FIRST")

    def second(event):
        del event
        calls.append("SECOND")

    def third(event):
        del event
        calls.append("THIRD")

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        first,
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        second,
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        third,
    )

    bus.publish(
        make_event()
    )

    assert calls == [
        "FIRST",
        "SECOND",
        "THIRD",
    ]


def test_unrelated_handler_not_called() -> None:
    bus = RuntimeEventBus()

    called = []

    def signal_handler(event):
        del event
        called.append("SIGNAL")

    def position_handler(event):
        del event
        called.append("POSITION")

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        signal_handler,
    )

    bus.subscribe(
        RuntimeEventType.POSITION_OPENED,
        position_handler,
    )

    bus.publish(
        make_event(
            RuntimeEventType.SIGNAL_CREATED
        )
    )

    assert called == [
        "SIGNAL"
    ]


def test_publish_without_subscribers_is_successful() -> None:
    bus = RuntimeEventBus()

    result = bus.publish(
        make_event()
    )

    assert result.subscriber_count == 0
    assert result.delivered_count == 0
    assert result.failures == ()
    assert result.successful is True


# ============================================================
# Strict failure handling
# ============================================================


def test_strict_bus_raises_on_handler_failure() -> None:
    bus = RuntimeEventBus(
        strict=True
    )

    def failing_handler(event):
        del event

        raise RuntimeError(
            "component failed"
        )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        failing_handler,
    )

    with pytest.raises(
        RuntimeEventDispatchError,
        match=(
            "runtime event dispatch failed"
        ),
    ) as captured:
        bus.publish(
            make_event()
        )

    result = captured.value.result

    assert result.successful is False
    assert result.failed_count == 1

    assert isinstance(
        result.failures[0].exception,
        RuntimeError,
    )


def test_strict_bus_stops_after_first_failure() -> None:
    bus = RuntimeEventBus(
        strict=True
    )

    calls = []

    def first(event):
        del event
        calls.append("FIRST")

    def failure(event):
        del event
        calls.append("FAIL")

        raise RuntimeError(
            "stop dispatch"
        )

    def third(event):
        del event
        calls.append("THIRD")

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        first,
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        failure,
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        third,
    )

    with pytest.raises(
        RuntimeEventDispatchError
    ) as captured:
        bus.publish(
            make_event()
        )

    assert calls == [
        "FIRST",
        "FAIL",
    ]

    assert (
        captured.value.result
        .delivered_count
        == 1
    )


# ============================================================
# Non-strict failure handling
# ============================================================


def test_non_strict_bus_continues_after_failure() -> None:
    bus = RuntimeEventBus(
        strict=False
    )

    calls = []

    def first(event):
        del event
        calls.append("FIRST")

    def failure(event):
        del event
        calls.append("FAIL")

        raise RuntimeError(
            "handler failure"
        )

    def third(event):
        del event
        calls.append("THIRD")

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        first,
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        failure,
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        third,
    )

    result = bus.publish(
        make_event()
    )

    assert calls == [
        "FIRST",
        "FAIL",
        "THIRD",
    ]

    assert result.subscriber_count == 3
    assert result.delivered_count == 2
    assert result.failed_count == 1
    assert result.successful is False


# ============================================================
# Mutation during dispatch
# ============================================================


def test_unsubscribe_during_publish_does_not_modify_current_dispatch() -> None:
    bus = RuntimeEventBus()

    calls = []

    def second(event):
        del event
        calls.append("SECOND")

    def first(event):
        del event

        calls.append("FIRST")

        bus.unsubscribe(
            RuntimeEventType.SIGNAL_CREATED,
            second,
        )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        first,
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        second,
    )

    bus.publish(
        make_event()
    )

    # publish() uses a subscriber snapshot.
    assert calls == [
        "FIRST",
        "SECOND",
    ]

    calls.clear()

    bus.publish(
        make_event(
            event_id="EVENT-002"
        )
    )

    assert calls == [
        "FIRST"
    ]


def test_subscription_during_publish_applies_next_event() -> None:
    bus = RuntimeEventBus()

    calls = []

    def second(event):
        del event
        calls.append("SECOND")

    def first(event):
        del event

        calls.append("FIRST")

        bus.subscribe(
            RuntimeEventType.SIGNAL_CREATED,
            second,
        )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        first,
    )

    bus.publish(
        make_event()
    )

    assert calls == [
        "FIRST"
    ]

    calls.clear()

    bus.publish(
        make_event(
            event_id="EVENT-002"
        )
    )

    assert calls == [
        "FIRST",
        "SECOND",
    ]


# ============================================================
# Clear
# ============================================================


def test_clear_removes_all_subscriptions() -> None:
    bus = RuntimeEventBus()

    def handler(event):
        del event

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        handler,
    )

    bus.subscribe(
        RuntimeEventType.POSITION_OPENED,
        handler,
    )

    bus.clear()

    assert (
        bus.subscriber_count(
            RuntimeEventType.SIGNAL_CREATED
        )
        == 0
    )

    assert (
        bus.subscriber_count(
            RuntimeEventType.POSITION_OPENED
        )
        == 0
    )