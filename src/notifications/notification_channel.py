"""
Phoenix notification channel port.

Concrete transports such as Telegram belong behind this
interface. Core notification logic must not depend on one
provider.
"""

from __future__ import annotations

from typing import Protocol

from src.notifications.notification_types import (
    NotificationDeliveryResult,
    NotificationMessage,
)


class NotificationChannel(
    Protocol,
):
    """
    One outbound notification transport.
    """

    @property
    def name(
        self,
    ) -> str:
        ...

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        ...


__all__ = [
    "NotificationChannel",
]
