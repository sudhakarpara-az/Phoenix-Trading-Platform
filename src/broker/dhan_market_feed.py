"""
Dhan Market Feed Wrapper
"""

from __future__ import annotations

from dhanhq import MarketFeed

from src.market.tick_processor import TickProcessor


class DhanMarketFeed:
    """
    Wrapper around Dhan MarketFeed.
    """

    def __init__(
        self,
        dhan_context,
        instruments: list,
        processor: TickProcessor,
    ) -> None:

        self._processor = processor

        self._feed = MarketFeed(
            dhan_context=dhan_context,
            instruments=instruments,
            version="v2",
            on_connect=self._on_connect,
            on_ticks=self._on_ticks,
            on_close=self._on_close,
            on_error=self._on_error,
        )

    def start(self) -> None:
        """
        Start websocket.
        """
        self._feed.run_forever()

    def stop(self) -> None:
        """
        Disconnect websocket.
        """
        self._feed.disconnect()

    def _on_connect(self) -> None:
        print("✅ Connected to Dhan MarketFeed")

    def _on_close(self, *args) -> None:
        print("❌ MarketFeed disconnected")

    def _on_error(self, error) -> None:
        print(f"MarketFeed Error : {error}")

    def _on_ticks(self, ticks) -> None:
        """
        Receive live ticks from Dhan.
        """

        for tick in ticks:
            self._processor.process(tick)