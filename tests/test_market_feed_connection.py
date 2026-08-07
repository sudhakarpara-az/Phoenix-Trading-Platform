"""
Basic construction test for the Dhan market-feed pipeline.

This test verifies that the broker context, market-data service,
subscription manager, tick processor, and Dhan market-feed
objects can be created successfully.

It does not place any orders.
"""

from src.broker.dhan_broker import DhanBroker
from src.broker.dhan_market_feed import DhanMarketFeed

from src.market.market_cache import MarketCache
from src.market.market_data_service import MarketDataService
from src.market.market_types import Exchange, Instrument, TickType
from src.market.subscription_manager import SubscriptionManager
from src.market.tick_processor import TickProcessor


def test_market_feed_connection() -> None:
    # Broker / Dhan context
    broker = DhanBroker()
    context = broker.get_context()

    assert context is not None

    # Market data layer
    cache = MarketCache()

    service = MarketDataService(
        cache=cache,
    )

    # Subscription manager
    subscriptions = SubscriptionManager()

    nifty = Instrument(
        exchange=Exchange.IDX,
        symbol="NIFTY 50",
        security_id="13",
    )

    subscriptions.add(
        instrument=nifty,
        tick_type=TickType.LTP,
    )

    # Tick processor
    processor = TickProcessor(
        market_data_service=service,
        subscription_manager=subscriptions,
    )

    # Existing Dhan market-feed wrapper
    feed = DhanMarketFeed(
        dhan_context=context,
        instruments=[],
        processor=processor,
    )

    # Assertions
    assert feed is not None
    assert processor is not None
    assert subscriptions.count() == 1

    print()
    print("Dhan market-feed pipeline created successfully.")
    print(f"Instrument: {nifty.symbol}")
    print(f"Security ID: {nifty.security_id}")
    print(f"Subscription Type: {TickType.LTP.value}")


if __name__ == "__main__":
    test_market_feed_connection()