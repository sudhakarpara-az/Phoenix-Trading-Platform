"""
Build the daily strategy-instrument reference candle
for the KS Phoenix strategy.
"""

from __future__ import annotations

from datetime import date, datetime, time
from threading import RLock

from src.market.market_types import MarketTick
from src.strategy.strategy_types import ReferenceCandle


class ReferenceCandleBuilder:
    """
    Builds one immutable reference candle from normalized
    MarketTick objects for one configured strategy instrument.

    Phoenix reference-candle rules:

        - The strategy instrument must be explicitly configured.
        - The default reference candle starts at 09:15:00.
        - The default reference candle ends at 09:16:00.
        - 09:16:00 is excluded from the reference candle.
        - Only the configured instrument security ID is accepted.
        - Ticks before the reference window are ignored.
        - Ticks at or after window_end are ignored.
        - Ticks from another trading date are ignored.
        - Out-of-order ticks older than the last accepted tick
          are ignored.
        - Finalization is allowed only at or after window_end.
        - Once finalized, the candle cannot be changed.

    The 09:15-09:16 reference candle is separate from the later
    trading-monitor activation boundary.
    """

    def __init__(
        self,
        security_id: str,
        instrument_symbol: str,
        window_start: time = time(9, 15),
        window_end: time = time(9, 16),
    ) -> None:
        security_id = security_id.strip()
        instrument_symbol = instrument_symbol.strip()

        if not security_id:
            raise ValueError(
                "security_id cannot be empty"
            )

        if not instrument_symbol:
            raise ValueError(
                "instrument_symbol cannot be empty"
            )

        if window_end <= window_start:
            raise ValueError(
                "window_end must be after window_start"
            )

        self._security_id = security_id
        self._instrument_symbol = instrument_symbol

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
    def instrument_symbol(self) -> str:
        return self._instrument_symbol

    @property
    def window_start(self) -> time:
        return self._window_start

    @property
    def window_end(self) -> time:
        return self._window_end

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
        Process one market tick for the configured instrument.

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

            self._high = max(
                self._high,
                price,
            )

            self._low = min(
                self._low,
                price,
            )

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

        Finalization is allowed only at or after window_end.
        """

        with self._lock:
            if self._finalized is not None:
                return self._finalized

            if now.time() < self._window_end:
                raise RuntimeError(
                    "reference candle cannot be finalized "
                    "before window_end"
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
                instrument_security_id=self._security_id,
                instrument_symbol=self._instrument_symbol,
                start_time=start_time,
                end_time=end_time,
                open=self._open,
                high=self._high,
                low=self._low,
                close=self._close,
            )

            return self._finalized

    def get_candle(
        self,
    ) -> ReferenceCandle | None:
        """
        Return the finalized candle, if available.
        """

        with self._lock:
            return self._finalized

    def reset(self) -> None:
        """
        Clear all daily candle state.

        Instrument identity and window configuration remain
        unchanged so the builder can be reused on another day.
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