from src.notifications.notification_deduplicator import (
    NotificationEventDeduplicator,
)


def test_first_event_claimed_duplicate_rejected():
    guard = NotificationEventDeduplicator()

    assert guard.claim("EVENT-1") is True
    assert guard.claim("EVENT-1") is False

    assert guard.count == 1


def test_release_allows_retry():
    guard = NotificationEventDeduplicator()

    assert guard.claim("EVENT-1") is True
    assert guard.release("EVENT-1") is True

    assert guard.claim("EVENT-1") is True


def test_capacity_evicts_oldest():
    guard = NotificationEventDeduplicator(
        capacity=2
    )

    assert guard.claim("EVENT-1") is True
    assert guard.claim("EVENT-2") is True
    assert guard.claim("EVENT-3") is True

    assert guard.contains("EVENT-1") is False
    assert guard.contains("EVENT-2") is True
    assert guard.contains("EVENT-3") is True
