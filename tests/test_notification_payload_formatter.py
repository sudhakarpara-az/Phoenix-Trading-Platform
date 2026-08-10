from src.notifications.payload_formatter import (
    NotificationPayloadFormatter,
)


def test_whitelisted_mapping_fields_are_rendered():
    formatter = NotificationPayloadFormatter()

    result = formatter.format(
        {
            "entity_type": "POSITION",
            "entity_id": "POS-001",
            "status": "OPEN",
            "quantity": 65,
        }
    )

    assert result is not None
    assert "Entity: POSITION" in result
    assert "ID: POS-001" in result
    assert "Status: OPEN" in result
    assert "Qty: 65" in result


def test_unapproved_sensitive_fields_are_not_rendered():
    formatter = NotificationPayloadFormatter()

    result = formatter.format(
        {
            "entity_type": "ORDER",
            "entity_id": "ORD-001",
            "token": "SECRET-TOKEN",
            "password": "SECRET-PASSWORD",
            "chat_id": "123456",
        }
    )

    assert result is not None

    assert "SECRET-TOKEN" not in result
    assert "SECRET-PASSWORD" not in result
    assert "123456" not in result

    assert "Entity: ORDER" in result
    assert "ID: ORD-001" in result


def test_unknown_mapping_only_returns_none():
    formatter = NotificationPayloadFormatter()

    assert (
        formatter.format(
            {
                "private_field": "hidden",
            }
        )
        is None
    )


def test_plain_string_detail_is_supported():
    formatter = NotificationPayloadFormatter()

    assert (
        formatter.format(
            " database unavailable "
        )
        == "database unavailable"
    )
