"""
Dhan live market-feed adapter.

This module is the Dhan-specific boundary of the
Phoenix Trading Platform market-data subsystem.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dhanhq import MarketFeed

from src.market.feed_health_monitor import FeedHealthMonitor
from src.market.market_feed_engine import MarketFeedEngine
from src.market.market_types import Exchange, TickType
from src.market.message_dispatcher import MessageDispatcher
from src.market.subscription_manager import (
    MarketSubscription,
    SubscriptionManager,
)


MarketFeedFactory = Callable[..., Any]


class DhanWebSocketAdapter:
    """
    Adapter between Phoenix market-data abstractions
    and DhanHQ MarketFeed.

    No strategy, execution, cache, or position logic
    belongs in this class.
    """

    def __init__(
        self,
        dhan_context: Any,
        subscription_manager: SubscriptionManager,
        feed_engine: MarketFeedEngine,
        health_monitor: FeedHealthMonitor,
        dispatcher: MessageDispatcher,
        market_feed_factory: MarketFeedFactory = MarketFeed,
        version: str = "v2",
    ) -> None:
        self._dhan_context = dhan_context
        self._subscriptions = subscription_manager
        self._feed_engine = feed_engine
        self._health_monitor = health_monitor
        self._dispatcher = dispatcher
        self._market_feed_factory = market_feed_factory
        self._version = version

        self._feed: Any | None = None

    @property
    def feed(self) -> Any | None:
        """Return the underlying Dhan feed instance."""

        return self._feed

    def build_dhan_instruments(
        self,
    ) -> list[tuple[int, str, int]]:
        """
        Convert Phoenix subscriptions into Dhan tuples.

        Dhan format:
            (
                exchange_segment,
                security_id,
                subscription_type,
            )
        """

        return [
            self._to_dhan_tuple(subscription)
            for subscription in self._subscriptions.list_all()
        ]

    def create_feed(self) -> None:
        """
        Create the Dhan MarketFeed instance.

        Creating the object is separate from running the
        WebSocket so lifecycle management remains testable.
        """

        instruments = self.build_dhan_instruments()

        if not instruments:
            raise RuntimeError(
                "Cannot create Dhan market feed "
                "without subscriptions"
            )

        self._feed_engine.set_connecting()

        try:
            self._feed = self._market_feed_factory(
                self._dhan_context,
                instruments,
                self._version,
            )

        except Exception as exc:
            self._record_error(exc)
            raise

    def run(self) -> None:
        """
        Start the Dhan MarketFeed event loop.

        This call may block depending on the Dhan SDK lifecycle.
        A worker/service will own this call during integration.
        """

        if self._feed is None:
            raise RuntimeError(
                "Dhan market feed has not been created"
            )

        try:
            self._feed_engine.set_connected()
            self._health_monitor.mark_connected()

            self._feed.run_forever()

        except Exception as exc:
            self._health_monitor.mark_disconnected()
            self._record_error(exc)
            raise

    def read_and_dispatch(self) -> Any:
        """
        Read one available Dhan message and dispatch it.

        The adapter deliberately does not parse the packet.
        """

        if self._feed is None:
            raise RuntimeError(
                "Dhan market feed has not been created"
            )

        try:
            message = self._feed.get_data()

            if message is None:
                return None

            self._feed_engine.mark_message_received()
            self._health_monitor.mark_message_received()

            self._dispatcher.dispatch(message)

            return message

        except Exception as exc:
            self._record_error(exc)
            raise

    def subscribe_current(self) -> None:
        """
        Subscribe current Phoenix subscriptions on an
        already-created Dhan feed.
        """

        if self._feed is None:
            raise RuntimeError(
                "Dhan market feed has not been created"
            )

        instruments = self.build_dhan_instruments()

        if not instruments:
            return

        try:
            self._feed.subscribe_symbols(instruments)
            self._feed_engine.set_subscribed()

        except Exception as exc:
            self._record_error(exc)
            raise

    def unsubscribe_current(self) -> None:
        """
        Remove current Phoenix subscriptions from Dhan.
        """

        if self._feed is None:
            raise RuntimeError(
                "Dhan market feed has not been created"
            )

        instruments = self.build_dhan_instruments()

        if not instruments:
            return

        try:
            self._feed.unsubscribe_symbols(instruments)

        except Exception as exc:
            self._record_error(exc)
            raise

    def disconnect(self) -> None:
        """Close the active Dhan market-feed connection."""

        if self._feed is None:
            self._feed_engine.set_disconnected()
            self._health_monitor.mark_disconnected()
            return

        try:
            self._feed.disconnect()

        finally:
            self._feed = None

            self._feed_engine.set_disconnected()
            self._health_monitor.mark_disconnected()

    def is_connected(self) -> bool:
        """Return Phoenix's current feed connection state."""

        return self._feed_engine.is_connected()

    def _record_error(self, exc: Exception) -> None:
        message = str(exc).strip() or exc.__class__.__name__

        self._feed_engine.set_error(message)
        self._health_monitor.mark_error(message)

    @staticmethod
    def _to_dhan_tuple(
        subscription: MarketSubscription,
    ) -> tuple[int, str, int]:

        exchange_segment = (
            DhanWebSocketAdapter._map_exchange(
                subscription.instrument.exchange
            )
        )

        subscription_type = (
            DhanWebSocketAdapter._map_tick_type(
                subscription.tick_type
            )
        )

        return (
            exchange_segment,
            subscription.instrument.security_id,
            subscription_type,
        )

    @staticmethod
    def _map_exchange(exchange: Exchange) -> int:
        mapping = {
            Exchange.NSE: MarketFeed.NSE,
            Exchange.NFO: MarketFeed.NSE_FNO,
            Exchange.BSE: MarketFeed.BSE,
            Exchange.MCX: MarketFeed.MCX,
        }

        try:
            return mapping[exchange]

        except KeyError as exc:
            raise ValueError(
                f"Unsupported Dhan exchange: {exchange}"
            ) from exc

    @staticmethod
    def _map_tick_type(tick_type: TickType) -> int:
        mapping = {
            TickType.LTP: MarketFeed.Ticker,
            TickType.QUOTE: MarketFeed.Quote,
            TickType.FULL: MarketFeed.Full,
        }

        try:
            return mapping[tick_type]

        except KeyError as exc:
            raise ValueError(
                f"Unsupported Dhan tick type: {tick_type}"
            ) from exc