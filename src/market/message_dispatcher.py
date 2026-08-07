"""
Thread-safe raw market message dispatcher.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any


MessageHandler = Callable[[Any], None]


class MessageDispatcher:
    """
    Dispatches incoming raw market messages to registered handlers.

    The dispatcher does not parse messages and does not contain
    broker-specific logic.
    """

    def __init__(self) -> None:
        self._handlers: list[MessageHandler] = []
        self._lock = RLock()

    def register(self, handler: MessageHandler) -> None:
        """
        Register a message handler.

        Duplicate handler registration is ignored.
        """

        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

    def unregister(self, handler: MessageHandler) -> bool:
        """
        Remove a registered handler.

        Returns True if the handler existed.
        """

        with self._lock:
            try:
                self._handlers.remove(handler)
                return True
            except ValueError:
                return False

    def dispatch(self, message: Any) -> None:
        """
        Dispatch one message to all currently registered handlers.

        A snapshot is used so handlers may register or unregister
        during dispatch without corrupting iteration.
        """

        with self._lock:
            handlers = tuple(self._handlers)

        for handler in handlers:
            handler(message)

    def count(self) -> int:
        """Return number of registered handlers."""

        with self._lock:
            return len(self._handlers)

    def clear(self) -> None:
        """Remove all registered handlers."""

        with self._lock:
            self._handlers.clear()