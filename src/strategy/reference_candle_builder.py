"""
Build the daily 09:15–09:20 NIFTY reference candle
for the KS Phoenix strategy.
"""

from __future__ import annotations

from datetime import date, datetime, time
from threading import RLock

from src.market.market_types import MarketTick
from src.strategy.strategy_types import ReferenceCandle


class ReferenceCandleBuilder:
    """
    Builds one immutable 09:15–09:20 reference candle
    from normalized NIFTY MarketTick objects.

    Rules:
        - Accept only the configured NIFTY security ID.
        - Accept ticks from 09:15:00 inclusive.
        - Accept ticks before 09:20:00.
        - Ignore ticks outside the reference window.
        - Ignore ticks from another trading date.
        - Ignore out-of-order ticks older than the last accepted tick.
        - Finalize only at or after 09:20.
        - Once finalized, the candle cannot be changed.
    """

    def __init__(
        self,
        security_id: str = "13",
        window_start: time = time(9, 15),
        window_end: time = time(9, 20),
    ) -> None:
        security_id = security_id.strip()

        if not security_id:
            raise ValueError("security_id cannot be empty")

        if window_end <= window_start:
            raise ValueError(
                "window_end must be after window_start"
            )

        self._security_id = security_id
        self._window_start = window_start
        self._window_end = window_end

        self._trading_date: date | None = None

        self._open: float | None = None
        self._high: float | None = None
        self._low: float | None = None
        self._close: float | None = None

        self._first_tick_at: datetime | None = None
        self._last_tick_at: datetime | None = None

        self._tick_count = 0

        self._finalized: ReferenceCandle | None = None

        self._lock = RLock()

    @property
    def security_id(self) -> str:
        return self._security_id

    @property
    def trading_date(self) -> date | None:
        with self._lock:
            return self._trading_date

    @property
    def tick_count(self) -> int:
        with self._lock:
            return self._tick_count

    @property
    def is_finalized(self) -> bool:
        with self._lock:
            return self._finalized is not None

    def process_tick(
        self,
        tick: MarketTick,
    ) -> bool:
        """
        Process one NIFTY market tick.

        Returns True when the tick was accepted into the candle.
        Returns False when it was ignored.
        """

        with self._lock:
            if self._finalized is not None:
                return False

            if tick.security_id != self._security_id:
                return False

            tick_time = tick.timestamp.time()

            if tick_time < self._window_start:
                return False

            if tick_time >= self._window_end:
                return False

            tick_date = tick.timestamp.date()

            if self._trading_date is None:
                self._trading_date = tick_date

            if tick_date != self._trading_date:
                return False

            # Protect OHLC construction against delayed/out-of-order
            # WebSocket messages.
            if (
                self._last_tick_at is not None
                and tick.timestamp < self._last_tick_at
            ):
                return False

            price = tick.ltp

            if self._open is None:
                self._open = price
                self._high = price
                self._low = price
                self._close = price

                self._first_tick_at = tick.timestamp
                self._last_tick_at = tick.timestamp

                self._tick_count = 1

                return True

            assert self._high is not None
            assert self._low is not None

            self._high = max(self._high, price)
            self._low = min(self._low, price)
            self._close = price

            self._last_tick_at = tick.timestamp
            self._tick_count += 1

            return True

    def finalize(
        self,
        now: datetime,
    ) -> ReferenceCandle:
        """
        Finalize and return the completed reference candle.

        Finalization is allowed only at or after 09:20.
        """

        with self._lock:
            if self._finalized is not None:
                return self._finalized

            if now.time() < self._window_end:
                raise RuntimeError(
                    "reference candle cannot be finalized before window_end"
                )

            if self._trading_date is None:
                raise RuntimeError(
                    "reference candle has no market ticks"
                )

            if now.date() != self._trading_date:
                raise RuntimeError(
                    "finalization date does not match trading date"
                )

            if (
                self._open is None
                or self._high is None
                or self._low is None
                or self._close is None
            ):
                raise RuntimeError(
                    "reference candle OHLC is incomplete"
                )

            start_time = datetime.combine(
                self._trading_date,
                self._window_start,
            )

            end_time = datetime.combine(
                self._trading_date,
                self._window_end,
            )

            self._finalized = ReferenceCandle(
                trading_date=self._trading_date,
                start_time=start_time,
                end_time=end_time,
                open=self._open,
                high=self._high,
                low=self._low,
                close=self._close,
            )

            return self._finalized

    def get_candle(self) -> ReferenceCandle | None:
        """Return the finalized candle, if available."""

        with self._lock:
            return self._finalized

    def reset(self) -> None:
        """
        Clear all state.

        Used when a new trading session begins.
        """

        with self._lock:
            self._trading_date = None

            self._open = None
            self._high = None
            self._low = None
            self._close = None

            self._first_tick_at = None
            self._last_tick_at = None

            self._tick_count = 0

            self._finalized = None