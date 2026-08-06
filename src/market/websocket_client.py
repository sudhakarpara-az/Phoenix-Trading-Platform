"""
WebSocket Client

Base class for broker websocket communication.
"""

from __future__ import annotations

from src.market.tick_processor import TickProcessor


class WebSocketClient:
    """
    Base websocket client.

    Actual Dhan implementation will be added later.
    """

    def __init__(self, processor: TickProcessor):
        self._processor = processor
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        """
        Connect to broker websocket.
        """
        print("Connecting to broker websocket...")
        self._connected = True

    def disconnect(self) -> None:
        """
        Disconnect websocket.
        """
        print("Disconnecting websocket...")
        self._connected = False

    def on_tick(self, raw_tick: dict) -> None:
        """
        Process incoming raw tick.
        """
        self._processor.process(raw_tick)