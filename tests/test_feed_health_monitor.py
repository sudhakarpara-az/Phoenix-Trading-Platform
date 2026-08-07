from datetime import datetime, timedelta

import pytest

from src.market.feed_health_monitor import (
    FeedHealthMonitor,
    FeedHealthState,
)


def test_initial_state_is_disconnected() -> None:
    monitor = FeedHealthMonitor()

    assert monitor.state() is FeedHealthState.DISCONNECTED


def test_connected_without_messages_is_stale() -> None:
    monitor = FeedHealthMonitor()

    monitor.mark_connected()

    assert monitor.state() is FeedHealthState.STALE


def test_recent_message_is_healthy() -> None:
    monitor = FeedHealthMonitor(stale_after_seconds=5)

    now = datetime.now()

    monitor.mark_connected()
    monitor.mark_message_received(now)

    assert (
        monitor.state(now + timedelta(seconds=4))
        is FeedHealthState.HEALTHY
    )


def test_old_message_is_stale() -> None:
    monitor = FeedHealthMonitor(stale_after_seconds=5)

    now = datetime.now()

    monitor.mark_connected()
    monitor.mark_message_received(now)

    assert (
        monitor.state(now + timedelta(seconds=6))
        is FeedHealthState.STALE
    )


def test_message_counter_increments() -> None:
    monitor = FeedHealthMonitor()

    monitor.mark_connected()

    monitor.mark_message_received()
    monitor.mark_message_received()
    monitor.mark_message_received()

    snapshot = monitor.snapshot()

    assert snapshot.messages_received == 3


def test_reconnect_counter_increments() -> None:
    monitor = FeedHealthMonitor()

    monitor.mark_reconnect()
    monitor.mark_reconnect()

    snapshot = monitor.snapshot()

    assert snapshot.reconnect_count == 2


def test_error_state_has_priority() -> None:
    monitor = FeedHealthMonitor()

    monitor.mark_connected()
    monitor.mark_message_received()

    monitor.mark_error("Feed failure")

    assert monitor.state() is FeedHealthState.ERROR
    assert monitor.snapshot().error == "Feed failure"


def test_clear_error_restores_health() -> None:
    monitor = FeedHealthMonitor()

    monitor.mark_connected()
    monitor.mark_message_received()

    monitor.mark_error("Temporary error")
    monitor.clear_error()

    assert monitor.state() is FeedHealthState.HEALTHY


def test_mark_disconnected_changes_state() -> None:
    monitor = FeedHealthMonitor()

    monitor.mark_connected()
    monitor.mark_message_received()

    monitor.mark_disconnected()

    assert monitor.state() is FeedHealthState.DISCONNECTED


def test_invalid_stale_timeout_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="stale_after_seconds must be greater than zero",
    ):
        FeedHealthMonitor(stale_after_seconds=0)


def test_empty_error_message_is_rejected() -> None:
    monitor = FeedHealthMonitor()

    with pytest.raises(
        ValueError,
        match="error message cannot be empty",
    ):
        monitor.mark_error(" ")