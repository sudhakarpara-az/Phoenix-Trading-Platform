"""
Phoenix fail-isolated notification dispatcher.

A notification transport is an observability dependency, not a
trading correctness dependency.

Therefore channel failures are converted into delivery results
and logged. They do not propagate into RuntimeEventBus and must
never interrupt execution, risk, recovery, force exit, or
application lifecycle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from src.core.logger import logger
from src.notifications.notification_channel import (
    NotificationChannel,
)
from src.notifications.notification_types import (
    NotificationDeliveryResult,
    NotificationDispatchResult,
    NotificationMessage,
)


class NotificationDispatcher:
    """
    Fan one notification out to zero or more channels.

    Channels are attempted independently. Failure of one channel
    does not prevent later channels from being attempted.
    """

    def __init__(
        self,
        *,
        channels: Iterable[
            NotificationChannel
        ] = (),
    ) -> None:
        self._channels = tuple(
            channels
        )

    @property
    def channels(
        self,
    ) -> tuple[
        NotificationChannel,
        ...,
    ]:
        return self._channels

    def dispatch(
        self,
        message: NotificationMessage,
        *,
        dispatched_at: datetime | None = None,
    ) -> NotificationDispatchResult:
        if not isinstance(
            message,
            NotificationMessage,
        ):
            raise TypeError(
                "message must be NotificationMessage"
            )

        attempted_at = (
            dispatched_at
            if dispatched_at is not None
            else datetime.now()
        )

        if type(attempted_at) is not datetime:
            raise TypeError(
                "dispatched_at must be a datetime"
            )

        deliveries: list[
            NotificationDeliveryResult
        ] = []

        for index, channel in enumerate(
            self._channels
        ):
            channel_name = (
                self._safe_channel_name(
                    channel,
                    index=index,
                )
            )

            try:
                result = channel.send(
                    message
                )

                if not isinstance(
                    result,
                    NotificationDeliveryResult,
                ):
                    raise TypeError(
                        "notification channel returned "
                        "invalid delivery result"
                    )

                deliveries.append(
                    result
                )

                if not result.success:
                    logger.warning(
                        "notification delivery failed "
                        f"channel={result.channel} "
                        f"notification_id="
                        f"{message.notification_id} "
                        f"error={result.error}"
                    )

            except Exception as exc:
                error = (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                logger.error(
                    "notification channel exception "
                    f"channel={channel_name} "
                    f"notification_id="
                    f"{message.notification_id} "
                    f"error={error}"
                )

                deliveries.append(
                    NotificationDeliveryResult(
                        channel=channel_name,
                        success=False,
                        attempted_at=attempted_at,
                        error=error,
                    )
                )

        return NotificationDispatchResult(
            message=message,
            deliveries=tuple(
                deliveries
            ),
        )

    @staticmethod
    def _safe_channel_name(
        channel: NotificationChannel,
        *,
        index: int,
    ) -> str:
        try:
            name = channel.name

            if (
                isinstance(name, str)
                and name.strip()
            ):
                return name.strip()

        except Exception:
            pass

        return (
            f"CHANNEL-{index + 1}"
        )


__all__ = [
    "NotificationDispatcher",
]
