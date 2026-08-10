"""
Safe Phoenix notification payload formatting.

RuntimeEvent.payload is intentionally opaque. Notification
formatting therefore uses an explicit whitelist rather than
serializing arbitrary dictionaries or domain objects.

This prevents accidental exposure of:
    - broker credentials,
    - tokens,
    - account secrets,
    - large internal objects,
    - future sensitive runtime fields.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping


class NotificationPayloadFormatter:
    """
    Convert a small set of operational payload fields into
    human-readable notification detail.
    """

    _FIELD_ORDER = (
        "entity_type",
        "entity_id",
        "status",
        "state",
        "component",
        "failure_code",
        "reason",
        "message",
        "symbol",
        "option_type",
        "level",
        "quantity",
        "filled_quantity",
        "price",
        "average_fill_price",
        "position_id",
        "order_intent_id",
        "signal_id",
    )

    _LABELS = {
        "entity_type": "Entity",
        "entity_id": "ID",
        "status": "Status",
        "state": "State",
        "component": "Component",
        "failure_code": "Failure",
        "reason": "Reason",
        "message": "Message",
        "symbol": "Symbol",
        "option_type": "Option",
        "level": "Level",
        "quantity": "Qty",
        "filled_quantity": "Filled Qty",
        "price": "Price",
        "average_fill_price": "Avg Fill",
        "position_id": "Position",
        "order_intent_id": "Order",
        "signal_id": "Signal",
    }

    def format(
        self,
        payload: object,
    ) -> str | None:
        if payload is None:
            return None

        if isinstance(
            payload,
            str,
        ):
            value = payload.strip()

            return (
                value[:500]
                if value
                else None
            )

        if isinstance(
            payload,
            Mapping,
        ):
            return self._format_mapping(
                payload
            )

        return self._format_object(
            payload
        )

    def _format_mapping(
        self,
        payload: Mapping[
            object,
            object,
        ],
    ) -> str | None:
        details: list[str] = []

        for field in self._FIELD_ORDER:
            if field not in payload:
                continue

            rendered = self._render_value(
                payload[field]
            )

            if rendered is None:
                continue

            label = self._LABELS[
                field
            ]

            details.append(
                f"{label}: {rendered}"
            )

        if not details:
            return None

        return " | ".join(
            details
        )[:1000]

    def _format_object(
        self,
        payload: object,
    ) -> str | None:
        details: list[str] = []

        for field in self._FIELD_ORDER:
            try:
                value = getattr(
                    payload,
                    field,
                    None,
                )

            except Exception:
                continue

            rendered = self._render_value(
                value
            )

            if rendered is None:
                continue

            label = self._LABELS[
                field
            ]

            details.append(
                f"{label}: {rendered}"
            )

        if not details:
            return None

        return " | ".join(
            details
        )[:1000]

    @staticmethod
    def _render_value(
        value: object,
    ) -> str | None:
        if value is None:
            return None

        if isinstance(
            value,
            Enum,
        ):
            value = value.value

        else:
            nested_value = getattr(
                value,
                "value",
                value,
            )

            if nested_value is not value:
                value = nested_value

        if isinstance(
            value,
            bool,
        ):
            return (
                "YES"
                if value
                else "NO"
            )

        if isinstance(
            value,
            (
                int,
                float,
            ),
        ):
            return str(
                value
            )

        if isinstance(
            value,
            str,
        ):
            normalized = value.strip()

            if not normalized:
                return None

            return normalized[:250]

        return None


__all__ = [
    "NotificationPayloadFormatter",
]
