"""
M11 notification-domain tests.
"""

from datetime import datetime

import pytest

from src.notifications.notification_types import (
    NotificationCategory,
    NotificationDeliveryResult,
    NotificationDispatchResult,
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
    30,
)

RUNTIME_ID = RuntimeId(
    "PHOENIX:2026-08-10:M11"
)


def message() -> NotificationMessage:
    return NotificationMessage(
        notification_id=" NOTIFY:EVENT-001 ",
        runtime_id=RUNTIME_ID,
        source_event_id=" EVENT-001 ",
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
        title=" Entry order filled ",
        body=" Position entry completed. ",
        occurred_at=NOW,
        correlation_id=" TRADE-001 ",
    )


def test_notification_message_normalizes_text():
    item = message()

    assert (
        item.notification_id
        == "NOTIFY:EVENT-001"
    )

    assert (
        item.source_event_id
        == "EVENT-001"
    )

    assert (
        item.title
        == "Entry order filled"
    )

    assert (
        item.body
        == "Position entry completed."
    )

    assert (
        item.correlation_id
        == "TRADE-001"
    )


def test_notification_message_rejects_empty_title():
    with pytest.raises(
        ValueError,
        match=(
            "notification title cannot be empty"
        ),
    ):
        NotificationMessage(
            notification_id="NOTIFY:1",
            runtime_id=RUNTIME_ID,
            source_event_id="EVENT-1",
            event_type=(
                RuntimeEventType.RUNTIME_FAILED
            ),
            severity=(
                NotificationSeverity.CRITICAL
            ),
            category=(
                NotificationCategory.RUNTIME
            ),
            title=" ",
            body="failure",
            occurred_at=NOW,
        )


def test_successful_delivery_cannot_contain_error():
    with pytest.raises(
        ValueError,
        match=(
            "successful delivery cannot "
            "contain an error"
        ),
    ):
        NotificationDeliveryResult(
            channel="TEST",
            success=True,
            attempted_at=NOW,
            error="unexpected",
        )


def test_dispatch_result_counts_channels():
    item = message()

    result = NotificationDispatchResult(
        message=item,
        deliveries=(
            NotificationDeliveryResult(
                channel="ONE",
                success=True,
                attempted_at=NOW,
            ),
            NotificationDeliveryResult(
                channel="TWO",
                success=False,
                attempted_at=NOW,
                error="offline",
            ),
        ),
    )

    assert result.channel_count == 2
    assert result.successful_count == 1
    assert result.failed_count == 1
    assert result.successful is False
