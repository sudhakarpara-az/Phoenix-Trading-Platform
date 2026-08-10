"""
M11 Telegram transport tests.

No real Telegram request is performed.
"""

from __future__ import annotations

import json

from datetime import datetime
from urllib.request import Request

import pytest

from src.notifications.notification_types import (
    NotificationCategory,
    NotificationMessage,
    NotificationSeverity,
)
from src.notifications.telegram_channel import (
    TelegramNotificationChannel,
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
    0,
)


def message() -> NotificationMessage:
    return NotificationMessage(
        notification_id="NOTIFY:E-1",
        runtime_id=RuntimeId(
            "PHOENIX:2026-08-10:M11"
        ),
        source_event_id="E-1",
        event_type=(
            RuntimeEventType.RUNTIME_FAILED
        ),
        severity=(
            NotificationSeverity.CRITICAL
        ),
        category=(
            NotificationCategory.RUNTIME
        ),
        title="Phoenix runtime failure",
        body="Database unavailable.",
        occurred_at=NOW,
    )


def test_telegram_requires_credentials():
    with pytest.raises(
        ValueError,
        match="bot token",
    ):
        TelegramNotificationChannel(
            bot_token="",
            chat_id="CHAT",
        )

    with pytest.raises(
        ValueError,
        match="chat id",
    ):
        TelegramNotificationChannel(
            bot_token="TOKEN",
            chat_id="",
        )


def test_telegram_sends_plain_json():
    captured: dict[
        str,
        object,
    ] = {}

    def sender(
        request: Request,
        timeout_seconds: float,
        /,
    ) -> bytes:
        captured["url"] = (
            request.full_url
        )

        captured["timeout"] = (
            timeout_seconds
        )

        data = request.data

        assert isinstance(
            data,
            bytes,
        )

        captured["payload"] = (
            json.loads(
                data.decode(
                    "utf-8"
                )
            )
        )

        return b'{"ok": true}'

    channel = TelegramNotificationChannel(
        bot_token="BOT-TOKEN",
        chat_id="CHAT-123",
        request_sender=sender,
        timeout_seconds=2.5,
    )

    result = channel.send(
        message()
    )

    assert result.success is True

    assert (
        captured["url"]
        == (
            "https://api.telegram.org/"
            "botBOT-TOKEN/sendMessage"
        )
    )

    assert captured[
        "timeout"
    ] == 2.5

    payload = captured[
        "payload"
    ]

    assert isinstance(
        payload,
        dict,
    )

    assert (
        payload["chat_id"]
        == "CHAT-123"
    )

    text = payload["text"]

    assert isinstance(
        text,
        str,
    )

    assert (
        "Phoenix runtime failure"
        in text
    )

    assert (
        "RUNTIME_FAILED"
        in text
    )

    assert (
        "parse_mode"
        not in payload
    )


def test_telegram_api_failure_is_data_not_exception():
    def sender(
        request: Request,
        timeout_seconds: float,
        /,
    ) -> bytes:
        del request
        del timeout_seconds

        return (
            b'{"ok": false, '
            b'"description": "Forbidden"}'
        )

    channel = TelegramNotificationChannel(
        bot_token="TOKEN",
        chat_id="CHAT",
        request_sender=sender,
    )

    result = channel.send(
        message()
    )

    assert result.success is False
    assert result.error == "Forbidden"


def test_telegram_exception_redacts_credentials():
    def sender(
        request: Request,
        timeout_seconds: float,
        /,
    ) -> bytes:
        del request
        del timeout_seconds

        raise RuntimeError(
            "BOT-TOKEN failed for CHAT-123"
        )

    channel = TelegramNotificationChannel(
        bot_token="BOT-TOKEN",
        chat_id="CHAT-123",
        request_sender=sender,
    )

    result = channel.send(
        message()
    )

    assert result.success is False
    assert result.error is not None

    assert (
        "BOT-TOKEN"
        not in result.error
    )

    assert (
        "CHAT-123"
        not in result.error
    )

    assert "***" in result.error


def test_message_is_capped_below_telegram_limit():
    channel = TelegramNotificationChannel(
        bot_token="TOKEN",
        chat_id="CHAT",
        request_sender=(
            lambda request, timeout:
                b'{"ok": true}'
        ),
    )

    original = message()

    oversized = NotificationMessage(
        notification_id=(
            original.notification_id
        ),
        runtime_id=original.runtime_id,
        source_event_id=(
            original.source_event_id
        ),
        event_type=original.event_type,
        severity=original.severity,
        category=original.category,
        title=original.title,
        body="X" * 10000,
        occurred_at=original.occurred_at,
    )

    assert len(
        channel.format_message(
            oversized
        )
    ) == 4000

def test_telegram_formats_synthetic_daily_summary():
    original = message()

    summary = NotificationMessage(
        notification_id="NOTIFY:DAILY-SUMMARY",
        runtime_id=original.runtime_id,
        source_event_id="DAILY-SUMMARY",
        event_type=None,
        severity=(
            NotificationSeverity.INFO
        ),
        category=(
            NotificationCategory.SUMMARY
        ),
        title="Phoenix daily operational summary",
        body="Operational alerts: 4",
        occurred_at=NOW,
    )

    channel = TelegramNotificationChannel(
        bot_token="TOKEN",
        chat_id="CHAT",
        request_sender=(
            lambda request, timeout:
                b'{"ok": true}'
        ),
    )

    rendered = channel.format_message(
        summary
    )

    assert (
        "Event: DAILY_SUMMARY"
        in rendered
    )

    assert (
        "Category: SUMMARY"
        in rendered
    )

    assert (
        "Operational alerts: 4"
        in rendered
    )
