"""
Phoenix Telegram notification transport.

Telegram is an outbound operational-observability dependency.

This module does not:
    - contain trading strategy,
    - interact with Dhan,
    - subscribe to RuntimeEventBus,
    - change runtime state,
    - retry trading orders.

Production composition places this channel behind the bounded
QueuedNotificationChannel so Telegram network I/O never executes
inside Phoenix RuntimeEventBus publication.
"""

from __future__ import annotations

import json

from datetime import datetime
from typing import (
    Any,
    Protocol,
)
from urllib.request import (
    Request,
    urlopen,
)

from src.notifications.notification_types import (
    NotificationDeliveryResult,
    NotificationMessage,
)


class TelegramRequestSender(
    Protocol,
):
    """
    Injectable Telegram HTTP boundary.

    Positional-only parameters deliberately avoid structural
    Protocol coupling to test-double parameter names.
    """

    def __call__(
        self,
        request: Request,
        timeout_seconds: float,
        /,
    ) -> bytes:
        ...


class TelegramNotificationChannel:
    """
    Telegram Bot API notification channel.

    Network/API failures are represented as unsuccessful
    NotificationDeliveryResult values. They do not propagate
    into Phoenix runtime control flow.
    """

    API_ROOT = (
        "https://api.telegram.org"
    )

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        request_sender:
            TelegramRequestSender | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        if not isinstance(
            bot_token,
            str,
        ):
            raise TypeError(
                "Telegram bot token must be str"
            )

        if not isinstance(
            chat_id,
            str,
        ):
            raise TypeError(
                "Telegram chat id must be str"
            )

        token = bot_token.strip()
        chat = chat_id.strip()

        if not token:
            raise ValueError(
                "Telegram bot token cannot be empty"
            )

        if not chat:
            raise ValueError(
                "Telegram chat id cannot be empty"
            )

        if (
            isinstance(
                timeout_seconds,
                bool,
            )
            or not isinstance(
                timeout_seconds,
                (
                    int,
                    float,
                ),
            )
        ):
            raise TypeError(
                "timeout_seconds must be numeric"
            )

        normalized_timeout = float(
            timeout_seconds
        )

        if (
            normalized_timeout <= 0
            or normalized_timeout > 10
        ):
            raise ValueError(
                "timeout_seconds must be greater "
                "than 0 and at most 10"
            )

        self._bot_token = token
        self._chat_id = chat

        self._request_sender = (
            request_sender
            if request_sender is not None
            else self._default_request_sender
        )

        self._timeout_seconds = (
            normalized_timeout
        )

    @property
    def name(
        self,
    ) -> str:
        return "TELEGRAM"

    @property
    def timeout_seconds(
        self,
    ) -> float:
        return self._timeout_seconds

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        if not isinstance(
            message,
            NotificationMessage,
        ):
            raise TypeError(
                "message must be NotificationMessage"
            )

        attempted_at = datetime.now()

        try:
            request = self._build_request(
                message
            )

            raw_response = (
                self._request_sender(
                    request,
                    self._timeout_seconds,
                )
            )

            response = self._decode_response(
                raw_response
            )

            if response.get(
                "ok"
            ) is not True:
                description = response.get(
                    "description",
                    "Telegram API returned failure",
                )

                return NotificationDeliveryResult(
                    channel=self.name,
                    success=False,
                    attempted_at=attempted_at,
                    error=self._sanitize_error(
                        str(
                            description
                        )
                    ),
                )

            return NotificationDeliveryResult(
                channel=self.name,
                success=True,
                attempted_at=attempted_at,
            )

        except Exception as exc:
            return NotificationDeliveryResult(
                channel=self.name,
                success=False,
                attempted_at=attempted_at,
                error=self._sanitize_error(
                    (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )
                ),
            )

    def format_message(
        self,
        message: NotificationMessage,
    ) -> str:
        """
        Render plain Telegram text.

        No Telegram parse mode is used. Operational payload text
        therefore cannot accidentally inject Markdown or HTML.
        """

        event_name = (
            message.event_type.value
            if message.event_type is not None
            else "DAILY_SUMMARY"
        )

        text = "\n".join(
            (
                (
                    f"[{message.severity.value}] "
                    f"{message.title}"
                ),
                (
                    "Category: "
                    f"{message.category.value}"
                ),
                (
                    "Event: "
                    f"{event_name}"
                ),
                (
                    "Runtime: "
                    f"{message.runtime_id.value}"
                ),
                (
                    "Time: "
                    f"{message.occurred_at.isoformat()}"
                ),
                "",
                message.body,
            )
        )

        # Telegram sendMessage has a finite text limit.
        # Leave margin for future formatting additions.
        return text[:4000]

    def _build_request(
        self,
        message: NotificationMessage,
    ) -> Request:
        url = (
            f"{self.API_ROOT}/"
            f"bot{self._bot_token}/"
            "sendMessage"
        )

        payload = json.dumps(
            {
                "chat_id":
                    self._chat_id,

                "text":
                    self.format_message(
                        message
                    ),

                "disable_web_page_preview":
                    True,
            },
            ensure_ascii=False,
        ).encode(
            "utf-8"
        )

        return Request(
            url=url,
            data=payload,
            headers={
                "Content-Type":
                    "application/json",
            },
            method="POST",
        )

    @staticmethod
    def _decode_response(
        raw_response: bytes,
    ) -> dict[str, Any]:
        if not isinstance(
            raw_response,
            bytes,
        ):
            raise TypeError(
                "Telegram HTTP response must be bytes"
            )

        decoded = json.loads(
            raw_response.decode(
                "utf-8"
            )
        )

        if not isinstance(
            decoded,
            dict,
        ):
            raise ValueError(
                "Telegram API response must "
                "be a JSON object"
            )

        return decoded

    def _sanitize_error(
        self,
        value: str,
    ) -> str:
        sanitized = value.replace(
            self._bot_token,
            "***",
        )

        sanitized = sanitized.replace(
            self._chat_id,
            "***",
        )

        return sanitized[:1000]

    @staticmethod
    def _default_request_sender(
        request: Request,
        timeout_seconds: float,
        /,
    ) -> bytes:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            body = response.read()

        if not isinstance(
            body,
            bytes,
        ):
            raise TypeError(
                "Telegram response body must be bytes"
            )

        return body


__all__ = [
    "TelegramNotificationChannel",
    "TelegramRequestSender",
]
