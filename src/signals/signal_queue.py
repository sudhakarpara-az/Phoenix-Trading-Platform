"""
Thread-safe FIFO queue for Phoenix TradingSignal objects.

This queue separates signal generation from downstream
option selection and execution processing.
"""

from __future__ import annotations

from collections import deque
from threading import Condition, RLock
from typing import Deque

from src.signals.signal_types import TradingSignal


class SignalQueue:
    """
    Thread-safe FIFO queue for TradingSignal objects.

    Responsibilities:
        - Enqueue accepted signals.
        - Preserve FIFO ordering.
        - Allow non-blocking dequeue.
        - Allow optional blocking dequeue.
        - Expose queue size and empty state.
        - Support controlled clearing.

    No option-selection, execution, or broker logic belongs here.
    """

    def __init__(
        self,
        max_size: int | None = None,
    ) -> None:
        if max_size is not None and max_size <= 0:
            raise ValueError(
                "max_size must be greater than zero"
            )

        self._max_size = max_size
        self._queue: Deque[TradingSignal] = deque()

        self._lock = RLock()
        self._condition = Condition(self._lock)

    @property
    def max_size(self) -> int | None:
        return self._max_size

    def put(
        self,
        signal: TradingSignal,
    ) -> bool:
        """
        Add one signal to the queue.

        Returns:
            True  -> signal queued
            False -> queue is full
        """

        with self._condition:
            if (
                self._max_size is not None
                and len(self._queue) >= self._max_size
            ):
                return False

            self._queue.append(signal)

            self._condition.notify()

            return True

    def get(
        self,
        block: bool = False,
        timeout: float | None = None,
    ) -> TradingSignal | None:
        """
        Remove and return the oldest queued signal.

        Non-blocking mode:
            returns None immediately when empty.

        Blocking mode:
            waits until a signal becomes available or timeout expires.
        """

        if timeout is not None and timeout < 0:
            raise ValueError(
                "timeout cannot be negative"
            )

        with self._condition:
            if not block:
                if not self._queue:
                    return None

                return self._queue.popleft()

            if timeout is None:
                while not self._queue:
                    self._condition.wait()

            else:
                available = self._condition.wait_for(
                    lambda: bool(self._queue),
                    timeout=timeout,
                )

                if not available:
                    return None

            return self._queue.popleft()

    def peek(self) -> TradingSignal | None:
        """
        Return the oldest signal without removing it.
        """

        with self._lock:
            if not self._queue:
                return None

            return self._queue[0]

    def size(self) -> int:
        """
        Return number of queued signals.
        """

        with self._lock:
            return len(self._queue)

    def is_empty(self) -> bool:
        """
        Return True when the queue contains no signals.
        """

        with self._lock:
            return not self._queue

    def clear(self) -> int:
        """
        Remove all queued signals.

        Returns number of signals removed.
        """

        with self._condition:
            removed = len(self._queue)

            self._queue.clear()

            return removed

    def snapshot(
        self,
    ) -> tuple[TradingSignal, ...]:
        """
        Return an immutable FIFO snapshot of queued signals.
        """

        with self._lock:
            return tuple(self._queue)