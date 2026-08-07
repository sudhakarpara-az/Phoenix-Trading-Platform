from dhanhq import MarketFeed
import pytest

from src.market.dhan_websocket_adapter import DhanWebSocketAdapter
from src.market.feed_health_monitor import (
    FeedHealthMonitor,
    FeedHealthState,
)
from src.market.market_feed_engine import (
    FeedState,
    MarketFeedEngine,
)
from src.market.market_types import (
    Exchange,
    Instrument,
    TickType,
)
from src.market.message_dispatcher import MessageDispatcher
from src.market.subscription_manager import SubscriptionManager


class FakeDhanFeed:
    """
    Fake Dhan MarketFeed used for unit testing.

    No real broker connection is created.
    """

    def __init__(
        self,
        dhan_context,
        instruments,
        version,
    ) -> None:
        self.dhan_context = dhan_context
        self.instruments = instruments
        self.version = version

        self.run_called = False
        self.close_called = False

        self.subscribed = None
        self.unsubscribed = None

        self.next_message = {
            "type": "Ticker Data",
            "security_id": "13",
            "LTP": 25000.00,
        }

    def run_forever(self) -> None:
        self.run_called = True

    def get_data(self):
        return self.next_message

    def subscribe_symbols(self, instruments) -> None:
        self.subscribed = instruments

    def unsubscribe_symbols(self, instruments) -> None:
        self.unsubscribed = instruments

    def close_connection(self) -> None:
        """
        Matches the synchronous close method used by
        DhanWebSocketAdapter.disconnect().
        """
        self.close_called = True


def build_adapter():
    """
    Build a complete fake Phoenix market-feed stack.
    """

    subscriptions = SubscriptionManager()

    feed_engine = MarketFeedEngine(
        subscription_manager=subscriptions,
    )

    health_monitor = FeedHealthMonitor()

    dispatcher = MessageDispatcher()

    adapter = DhanWebSocketAdapter(
        dhan_context=object(),
        subscription_manager=subscriptions,
        feed_engine=feed_engine,
        health_monitor=health_monitor,
        dispatcher=dispatcher,
        market_feed_factory=FakeDhanFeed,
    )

    return (
        subscriptions,
        feed_engine,
        health_monitor,
        dispatcher,
        adapter,
    )


def add_nifty_subscription(
    subscriptions: SubscriptionManager,
) -> None:
    """
    Register NIFTY index subscription.

    NIFTY underlying uses Dhan IDX segment.
    """

    subscriptions.add(
        Instrument(
            exchange=Exchange.IDX,
            symbol="NIFTY 50",
            security_id="13",
        ),
        TickType.LTP,
    )


def test_nifty_index_maps_to_dhan_index_segment() -> None:
    subscriptions, _, _, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    instruments = adapter.build_dhan_instruments()

    assert instruments == [
        (
            MarketFeed.IDX,
            "13",
            MarketFeed.Ticker,
        )
    ]


def test_dhan_instrument_conversion() -> None:
    subscriptions, _, _, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    instruments = adapter.build_dhan_instruments()

    assert len(instruments) == 1

    exchange, security_id, tick_type = instruments[0]

    assert exchange == MarketFeed.IDX
    assert security_id == "13"
    assert tick_type == MarketFeed.Ticker


def test_create_feed_requires_subscription() -> None:
    _, _, _, _, adapter = build_adapter()

    with pytest.raises(
        RuntimeError,
        match="without subscriptions",
    ):
        adapter.create_feed()


def test_create_feed_creates_dhan_feed() -> None:
    subscriptions, feed_engine, _, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    adapter.create_feed()

    assert adapter.feed is not None
    assert adapter.feed.version == "v2"
    assert feed_engine.state() is FeedState.CONNECTING


def test_run_updates_connection_state() -> None:
    subscriptions, feed_engine, health, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    adapter.create_feed()
    adapter.run()

    assert adapter.feed is not None
    assert adapter.feed.run_called is True

    assert feed_engine.state() is FeedState.CONNECTED

    # Connected but no tick received yet.
    assert health.state() is FeedHealthState.STALE


def test_message_is_dispatched() -> None:
    subscriptions, _, health, dispatcher, adapter = build_adapter()

    received = []

    dispatcher.register(received.append)

    add_nifty_subscription(subscriptions)

    adapter.create_feed()
    adapter.run()

    message = adapter.read_and_dispatch()

    assert message is not None
    assert len(received) == 1

    assert received[0]["security_id"] == "13"
    assert received[0]["LTP"] == 25000.00

    assert health.snapshot().messages_received == 1


def test_read_message_marks_feed_healthy() -> None:
    subscriptions, _, health, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    adapter.create_feed()
    adapter.run()

    assert health.state() is FeedHealthState.STALE

    adapter.read_and_dispatch()

    assert health.state() is FeedHealthState.HEALTHY


def test_subscribe_current() -> None:
    subscriptions, feed_engine, _, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    adapter.create_feed()
    adapter.subscribe_current()

    assert adapter.feed is not None
    assert adapter.feed.subscribed is not None

    assert adapter.feed.subscribed == [
        (
            MarketFeed.IDX,
            "13",
            MarketFeed.Ticker,
        )
    ]

    assert feed_engine.state() is FeedState.SUBSCRIBED


def test_unsubscribe_current() -> None:
    subscriptions, _, _, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    adapter.create_feed()
    adapter.unsubscribe_current()

    assert adapter.feed is not None

    assert adapter.feed.unsubscribed == [
        (
            MarketFeed.IDX,
            "13",
            MarketFeed.Ticker,
        )
    ]


def test_disconnect() -> None:
    subscriptions, feed_engine, health, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    adapter.create_feed()
    adapter.run()

    feed = adapter.feed

    assert feed is not None

    adapter.disconnect()

    assert feed.close_called is True

    assert adapter.feed is None

    assert feed_engine.state() is FeedState.DISCONNECTED

    assert health.state() is FeedHealthState.DISCONNECTED


def test_disconnect_without_feed_is_safe() -> None:
    _, feed_engine, health, _, adapter = build_adapter()

    adapter.disconnect()

    assert adapter.feed is None

    assert feed_engine.state() is FeedState.DISCONNECTED

    assert health.state() is FeedHealthState.DISCONNECTED


def test_is_connected() -> None:
    subscriptions, _, _, _, adapter = build_adapter()

    add_nifty_subscription(subscriptions)

    adapter.create_feed()

    assert adapter.is_connected() is False

    adapter.run()

    assert adapter.is_connected() is True