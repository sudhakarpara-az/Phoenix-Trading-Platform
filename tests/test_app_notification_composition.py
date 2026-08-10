"""
M11 production notification composition tests.

No real Telegram request is performed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from urllib.request import Request

import pytest

from src.app.bootstrap import (
    compose_notification_foundation,
)
from src.app.container import (
    PhoenixRuntimeStartupContainer,
    build_notification_end_of_day,
    build_notification_foundation,
)
from src.notifications.queued_channel import (
    QueuedNotificationChannel,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.runtime_events import (
    RuntimeEventType,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeState,
)
from src.services.scheduler import (
    TradingDayEndOfDayCoordinator,
)


class RecordingOrchestrator:
    def __init__(
        self,
        *,
        state:
            RuntimeState = RuntimeState.CREATED,
    ) -> None:
        self.state = state

        self.runtime_id = RuntimeId(
            "PHOENIX:2026-08-10:M11"
        )

        self.registrations: list[
            tuple[
                object,
                int,
                bool,
            ]
        ] = []

    def register_component(
        self,
        *,
        component,
        order: int,
        critical: bool = True,
    ) -> None:
        self.registrations.append(
            (
                component,
                order,
                critical,
            )
        )


def runtime_startup(
    *,
    state:
        RuntimeState = RuntimeState.CREATED,
) -> tuple[
    PhoenixRuntimeStartupContainer,
    RuntimeEventBus,
    RecordingOrchestrator,
]:
    bus = RuntimeEventBus()

    orchestrator = (
        RecordingOrchestrator(
            state=state
        )
    )

    value = cast(
        PhoenixRuntimeStartupContainer,
        SimpleNamespace(
            event_bus=bus,
            orchestrator=orchestrator,
        ),
    )

    return (
        value,
        bus,
        orchestrator,
    )


def fake_sender(
    request: Request,
    timeout_seconds: float,
    /,
) -> bytes:
    del request
    del timeout_seconds

    return b'{"ok": true}'


def test_composition_uses_exact_runtime_bus():
    (
        startup,
        bus,
        orchestrator,
    ) = runtime_startup()

    container = (
        build_notification_foundation(
            runtime_startup=startup,
            telegram_enabled=True,
            telegram_bot_token="TOKEN",
            telegram_chat_id="CHAT",
            telegram_request_sender=(
                fake_sender
            ),
        )
    )

    assert (
        container.runtime_startup
        is startup
    )

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
            RuntimeEventType.RUNTIME_STOPPED
        )
        == 0
    )

    assert len(
        orchestrator.registrations
    ) == 1

    (
        component,
        order,
        critical,
    ) = orchestrator.registrations[0]

    assert isinstance(
        component,
        QueuedNotificationChannel,
    )

    assert (
        component
        is container.queued_channel
    )

    # Order 0 starts first and stops last.
    assert order == 0

    # Existing metadata still marks observability
    # infrastructure noncritical.
    assert critical is False


def test_disabled_telegram_has_no_runtime_side_effect():
    (
        startup,
        bus,
        orchestrator,
    ) = runtime_startup()

    container = (
        build_notification_foundation(
            runtime_startup=startup,
            telegram_enabled=False,
        )
    )

    assert (
        container.telegram_channel
        is None
    )

    assert (
        container.queued_channel
        is None
    )

    assert (
        container.subscribed_event_types
        == ()
    )

    assert (
        orchestrator.registrations
        == []
    )

    assert (
        bus.subscriber_count(
            RuntimeEventType.RUNTIME_FAILED
        )
        == 0
    )


def test_enabled_composition_requires_created_runtime():
    (
        startup,
        bus,
        orchestrator,
    ) = runtime_startup(
        state=RuntimeState.RUNNING
    )

    with pytest.raises(
        ValueError,
        match="CREATED",
    ):
        build_notification_foundation(
            runtime_startup=startup,
            telegram_enabled=True,
            telegram_bot_token="TOKEN",
            telegram_chat_id="CHAT",
        )

    # Precondition fails before either side effect.
    assert orchestrator.registrations == []

    assert (
        bus.subscriber_count(
            RuntimeEventType.RUNTIME_FAILED
        )
        == 0
    )


def test_bootstrap_reads_environment_at_call_time(
    monkeypatch,
):
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN",
        "ENV-TOKEN",
    )

    monkeypatch.setenv(
        "TELEGRAM_CHAT_ID",
        "ENV-CHAT",
    )

    (
        startup,
        _,
        orchestrator,
    ) = runtime_startup()

    http_calls = 0

    def sender(
        request: Request,
        timeout_seconds: float,
        /,
    ) -> bytes:
        nonlocal http_calls

        del request
        del timeout_seconds

        http_calls += 1

        return b'{"ok": true}'

    container = (
        compose_notification_foundation(
            runtime_startup=startup,
            telegram_enabled=True,
            telegram_request_sender=sender,
        )
    )

    assert (
        container.telegram_channel
        is not None
    )

    assert (
        container.queued_channel
        is not None
    )

    assert len(
        orchestrator.registrations
    ) == 1

    # Composition itself makes no Telegram request.
    assert http_calls == 0

def test_composition_shares_dedupe_formatter_and_summary():
    (
        startup,
        _,
        _,
    ) = runtime_startup()

    container = (
        build_notification_foundation(
            runtime_startup=startup,
            telegram_enabled=True,
            telegram_bot_token="TOKEN",
            telegram_chat_id="CHAT",
            telegram_request_sender=(
                fake_sender
            ),
        )
    )

    assert (
        container.subscriber.deduplicator
        is container.deduplicator
    )

    assert (
        container.subscriber.payload_formatter
        is container.payload_formatter
    )

    assert (
        container.dispatcher.channels[0]
        is container.summary_collector
    )

    assert (
        container.dispatcher.channels[1]
        is container.queued_channel
    )

def test_eod_composition_reuses_notification_summary_service():
    (
        startup,
        _,
        _,
    ) = runtime_startup()

    notification = (
        build_notification_foundation(
            runtime_startup=startup,
            telegram_enabled=True,
            telegram_bot_token="TOKEN",
            telegram_chat_id="CHAT",
            telegram_request_sender=(
                fake_sender
            ),
        )
    )

    fake_eod = cast(
        TradingDayEndOfDayCoordinator,
        SimpleNamespace(
            evaluate=lambda **kwargs: None
        ),
    )

    composed = build_notification_end_of_day(
        notification=notification,
        end_of_day_coordinator=fake_eod,
    )

    assert (
        composed.summary_service
        is notification.summary_service
    )

    assert (
        composed.runtime_id
        == startup.orchestrator.runtime_id
    )
