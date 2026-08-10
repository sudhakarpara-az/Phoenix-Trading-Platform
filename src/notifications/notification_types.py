"""
Phoenix notification domain types.

These types contain no Telegram, HTTP, Dhan, database, or
application-composition logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.runtime.runtime_events import (
    RuntimeEventType,
)
from src.runtime.runtime_types import (
    RuntimeId,
)


class NotificationSeverity(str, Enum):
    """
    Operational importance of one notification.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class NotificationCategory(str, Enum):
    """
    High-level Phoenix notification domain.
    """

    RUNTIME = "RUNTIME"
    TRADE = "TRADE"
    RISK = "RISK"
    RECOVERY = "RECOVERY"
    HEALTH = "HEALTH"
    SUMMARY = "SUMMARY"


@dataclass(
    frozen=True,
    slots=True,
)
class NotificationMessage:
    """
    Immutable channel-independent notification.

    source_event_id preserves the originating Phoenix event
    identity so notification delivery remains traceable without
    creating a second business-event system.
    """

    notification_id: str

    runtime_id: RuntimeId

    source_event_id: str
    event_type: RuntimeEventType | None

    severity: NotificationSeverity
    category: NotificationCategory

    title: str
    body: str

    occurred_at: datetime

    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(
        self,
    ) -> None:
        notification_id = (
            self.notification_id.strip()
        )

        if not notification_id:
            raise ValueError(
                "notification_id cannot be empty"
            )

        source_event_id = (
            self.source_event_id.strip()
        )

        if not source_event_id:
            raise ValueError(
                "source_event_id cannot be empty"
            )

        if not isinstance(
            self.runtime_id,
            RuntimeId,
        ):
            raise TypeError(
                "runtime_id must be RuntimeId"
            )

        if (
            self.event_type is not None
            and not isinstance(
                self.event_type,
                RuntimeEventType,
            )
        ):
            raise TypeError(
                "event_type must be RuntimeEventType or None"
            )

        if not isinstance(
            self.severity,
            NotificationSeverity,
        ):
            raise TypeError(
                "severity must be NotificationSeverity"
            )

        if not isinstance(
            self.category,
            NotificationCategory,
        ):
            raise TypeError(
                "category must be NotificationCategory"
            )

        title = self.title.strip()

        if not title:
            raise ValueError(
                "notification title cannot be empty"
            )

        body = self.body.strip()

        if not body:
            raise ValueError(
                "notification body cannot be empty"
            )

        if type(self.occurred_at) is not datetime:
            raise TypeError(
                "occurred_at must be a datetime"
            )

        correlation_id = (
            _normalize_optional_text(
                self.correlation_id,
                name="correlation_id",
            )
        )

        causation_id = (
            _normalize_optional_text(
                self.causation_id,
                name="causation_id",
            )
        )

        object.__setattr__(
            self,
            "notification_id",
            notification_id,
        )

        object.__setattr__(
            self,
            "source_event_id",
            source_event_id,
        )

        object.__setattr__(
            self,
            "title",
            title,
        )

        object.__setattr__(
            self,
            "body",
            body,
        )

        object.__setattr__(
            self,
            "correlation_id",
            correlation_id,
        )

        object.__setattr__(
            self,
            "causation_id",
            causation_id,
        )


@dataclass(
    frozen=True,
    slots=True,
)
class NotificationDeliveryResult:
    """
    Result returned by one notification channel.

    Channel failures are data, not trading-runtime exceptions.
    """

    channel: str
    success: bool
    attempted_at: datetime

    error: str | None = None

    def __post_init__(
        self,
    ) -> None:
        channel = self.channel.strip()

        if not channel:
            raise ValueError(
                "notification channel cannot be empty"
            )

        if type(self.success) is not bool:
            raise TypeError(
                "success must be bool"
            )

        if type(self.attempted_at) is not datetime:
            raise TypeError(
                "attempted_at must be a datetime"
            )

        error = _normalize_optional_text(
            self.error,
            name="error",
        )

        if self.success and error is not None:
            raise ValueError(
                "successful delivery cannot contain an error"
            )

        object.__setattr__(
            self,
            "channel",
            channel,
        )

        object.__setattr__(
            self,
            "error",
            error,
        )


@dataclass(
    frozen=True,
    slots=True,
)
class NotificationDispatchResult:
    """
    Aggregate result across all configured channels.
    """

    message: NotificationMessage

    deliveries: tuple[
        NotificationDeliveryResult,
        ...,
    ]

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.message,
            NotificationMessage,
        ):
            raise TypeError(
                "message must be NotificationMessage"
            )

        if type(self.deliveries) is not tuple:
            raise TypeError(
                "deliveries must be a tuple"
            )

        for delivery in self.deliveries:
            if not isinstance(
                delivery,
                NotificationDeliveryResult,
            ):
                raise TypeError(
                    "deliveries must contain "
                    "NotificationDeliveryResult"
                )

    @property
    def channel_count(
        self,
    ) -> int:
        return len(
            self.deliveries
        )

    @property
    def successful_count(
        self,
    ) -> int:
        return sum(
            delivery.success
            for delivery in self.deliveries
        )

    @property
    def failed_count(
        self,
    ) -> int:
        return (
            self.channel_count
            - self.successful_count
        )

    @property
    def successful(
        self,
    ) -> bool:
        return self.failed_count == 0


def _normalize_optional_text(
    value: str | None,
    *,
    name: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(
        value,
        str,
    ):
        raise TypeError(
            f"{name} must be str or None"
        )

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{name} cannot be empty"
        )

    return normalized


__all__ = [
    "NotificationCategory",
    "NotificationDeliveryResult",
    "NotificationDispatchResult",
    "NotificationMessage",
    "NotificationSeverity",
]
