from datetime import datetime, timedelta

import pytest

from src.market.market_feed_engine import (
    FeedState,
    MarketFeedEngine,
)
from src.market.market_types import Exchange, Instrument
from src.market.subscription_manager import SubscriptionManager


def create_engine(
    stale_after_seconds: int = 5,
) -> MarketFeedEngine:
    return MarketFeedEngine(
        subscription_manager=SubscriptionManager(),
        stale_after_seconds=stale_after_seconds,
    )


def test_initial_state_is_disconnected() -> None:
    engine = create_engine()

    assert engine.state() is FeedState.DISCONNECTED
    assert engine.is_connected() is False


def test_connecting_state() -> None:
    engine = create_engine()

    engine.set_connecting()

    assert engine.state() is FeedState.CONNECTING


def test_connected_state() -> None:
    engine = create_engine()

    engine.set_connected()

    assert engine.state() is FeedState.CONNECTED
    assert engine.is_connected() is True


def test_subscribed_state_is_connected() -> None:
    engine = create_engine()

    engine.set_subscribed()

    assert engine.state() is FeedState.SUBSCRIBED
    assert engine.is_connected() is True


def test_disconnected_state() -> None:
    engine = create_engine()

    engine.set_connected()
    engine.set_disconnected()

    assert engine.state() is FeedState.DISCONNECTED
    assert engine.is_connected() is False


def test_error_state() -> None:
    engine = create_engine()

    engine.set_error("WebSocket disconnected")

    health = engine.health()

    assert engine.state() is FeedState.ERROR
    assert health.error == "WebSocket disconnected"


def test_empty_error_is_rejected() -> None:
    engine = create_engine()

    with pytest.raises(
        ValueError,
        match="error message cannot be empty",
    ):
        engine.set_error(" ")


def test_feed_is_stale_before_first_message() -> None:
    engine = create_engine()

    assert engine.is_stale() is True


def test_recent_message_is_not_stale() -> None:
    engine = create_engine(stale_after_seconds=5)

    now = datetime.now()

    engine.mark_message_received(now)

    assert engine.is_stale(now + timedelta(seconds=4)) is False


def test_old_message_is_stale() -> None:
    engine = create_engine(stale_after_seconds=5)

    now = datetime.now()

    engine.mark_message_received(now)

    assert engine.is_stale(now + timedelta(seconds=6)) is True


def test_health_includes_subscription_count() -> None:
    subscriptions = SubscriptionManager()

    subscriptions.add(
        Instrument(
            exchange=Exchange.NSE,
            symbol="NIFTY 50",
            security_id="13",
        )
    )

    engine = MarketFeedEngine(subscriptions)

    health = engine.health()

    assert health.subscription_count == 1


def test_invalid_stale_timeout_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="stale_after_seconds must be greater than zero",
    ):
        create_engine(stale_after_seconds=0)