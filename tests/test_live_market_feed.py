"""
Live Dhan Market Feed integration test.

This validates the complete Phoenix market-data pipeline:

Dhan MarketFeed
    -> DhanWebSocketAdapter
    -> MessageDispatcher
    -> TickProcessor
    -> MarketTick
    -> MarketDataService
    -> MarketCache

Run manually during market hours:

    python -m pytest tests/test_live_market_feed.py -v -s
"""

from __future__ import annotations

import os
import time

import pytest
from dhanhq import DhanContext
from dotenv import load_dotenv

from src.market.dhan_websocket_adapter import DhanWebSocketAdapter
from src.market.feed_health_monitor import FeedHealthMonitor
from src.market.market_cache import MarketCache
from src.market.market_data_service import MarketDataService
from src.market.market_feed_engine import MarketFeedEngine
from src.market.market_types import Exchange, Instrument, TickType
from src.market.message_dispatcher import MessageDispatcher
from src.market.subscription_manager import SubscriptionManager
from src.market.tick_processor import TickProcessor


load_dotenv()

pytestmark = pytest.mark.integration


def require_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        pytest.skip(f"{name} is not configured")

    return value


def test_live_nifty_market_feed() -> None:
    # --------------------------------------------------
    # Dhan credentials
    # --------------------------------------------------

    client_id = require_env("DHAN_CLIENT_ID")
    access_token = require_env("DHAN_ACCESS_TOKEN")

    dhan_context = DhanContext(
        client_id,
        access_token,
    )

    # --------------------------------------------------
    # Phoenix market-data infrastructure
    # --------------------------------------------------

    cache = MarketCache()

    market_data = MarketDataService(
        cache=cache,
    )

    subscriptions = SubscriptionManager()

    feed_engine = MarketFeedEngine(
        subscription_manager=subscriptions,
        stale_after_seconds=10,
    )

    health_monitor = FeedHealthMonitor(
        stale_after_seconds=10,
    )

    dispatcher = MessageDispatcher()

    tick_processor = TickProcessor(
        market_data_service=market_data,
        subscription_manager=subscriptions,
    )

    dispatcher.register(
        tick_processor.process,
    )

    # --------------------------------------------------
    # NIFTY underlying
    # --------------------------------------------------

    nifty = Instrument(
    exchange=Exchange.IDX,
    symbol="NIFTY 50",
    security_id="13",
)

    subscriptions.add(
        instrument=nifty,
        tick_type=TickType.LTP,
    )

    # --------------------------------------------------
    # Dhan WebSocket adapter
    # --------------------------------------------------

    adapter = DhanWebSocketAdapter(
        dhan_context=dhan_context,
        subscription_manager=subscriptions,
        feed_engine=feed_engine,
        health_monitor=health_monitor,
        dispatcher=dispatcher,
        version="v2",
    )

    print()
    print("=" * 60)
    print("PHOENIX LIVE MARKET FEED TEST")
    print("=" * 60)
    print(f"Instrument  : {nifty.symbol}")
    print(f"Security ID : {nifty.security_id}")
    print(f"Tick Type   : {TickType.LTP.value}")
    print("=" * 60)

    timeout_seconds = 30
    started_at = time.monotonic()

    try:
        adapter.create_feed()

        while time.monotonic() - started_at < timeout_seconds:

            # Dhan SDK feed processing cycle
            adapter.run()

            raw_message = adapter.read_and_dispatch()

            if raw_message is None:
                time.sleep(0.1)
                continue

            print()
            print("RAW DHAN MESSAGE")
            print("----------------")
            print(raw_message)

            tick = market_data.get_tick(
                nifty.security_id
            )

            # Some incoming packets are not ticker packets.
            # TickProcessor intentionally ignores those.
            if tick is None:
                continue

            ltp = market_data.get_ltp(
                nifty.security_id
            )

            print()
            print("PHOENIX MARKET TICK")
            print("-------------------")
            print(tick)

            print()
            print(f"LIVE NIFTY LTP : {ltp}")

            print()
            print("FEED HEALTH")
            print("-----------")
            print(health_monitor.snapshot())

            assert tick.security_id == nifty.security_id
            assert tick.symbol == nifty.symbol
            assert tick.ltp > 0
            assert ltp is not None
            assert ltp > 0

            return

        pytest.fail(
            f"No valid NIFTY MarketTick received "
            f"within {timeout_seconds} seconds"
        )

    finally:
        adapter.disconnect()