"""
Live KS Phoenix K5/K6/K7 level monitor.

Consumes normalized MarketTick objects for one strategy
instrument and emits broker-independent LevelEvent objects
when that instrument touches or crosses an entry level.

No order, option-selection, position, or broker logic
belongs in this module.
"""

from __future__ import annotations

from datetime import date
from threading import RLock

from src.market.market_types import MarketTick
from src.strategy.daily_ks_level_service import (
    DailyKSLevelService,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    LevelEvent,
    LevelEventType,
)


class LevelMonitor:
    """
    Monitors one strategy instrument against K5, K6, and K7.

    Event rules:

        previous < level and current >= level
            -> CROSSED_UP

        previous > level and current <= level
            -> CROSSED_DOWN

        current == level without a directional cross
            -> TOUCHED

    Instrument identity is taken from the KS level set.

    An optional security_id may still be supplied for backward
    compatibility. When omitted, the monitor automatically uses
    the instrument security ID stored in KSLevels.
    """

    def __init__(
        self,
        level_service: DailyKSLevelService,
        security_id: str | None = None,
        touch_tolerance: float = 0.0,
    ) -> None:
        normalized_security_id: str | None = None

        if security_id is not None:
            normalized_security_id = security_id.strip()

            if not normalized_security_id:
                raise ValueError(
                    "security_id cannot be empty"
                )

        if touch_tolerance < 0:
            raise ValueError(
                "touch_tolerance cannot be negative"
            )

        self._level_service = level_service
        self._security_id = normalized_security_id
        self._touch_tolerance = touch_tolerance

        self._previous_price: float | None = None
        self._trading_date: date | None = None

        self._lock = RLock()

    @property
    def previous_price(self) -> float | None:
        with self._lock:
            return self._previous_price

    @property
    def trading_date(self) -> date | None:
        with self._lock:
            return self._trading_date

    @property
    def security_id(self) -> str | None:
        """
        Return an explicitly configured security ID.

        None means the monitor derives the instrument identity
        from the current KSLevels object.
        """

        return self._security_id

    def process_tick(
        self,
        tick: MarketTick,
    ) -> tuple[LevelEvent, ...]:
        """
        Process one live strategy-instrument tick.

        Returns zero or more LevelEvent objects.
        """

        with self._lock:
            levels = self._level_service.get_levels()

            if levels is None:
                return ()

            expected_security_id = (
                self._security_id
                or levels.instrument_security_id
            )

            # Fail closed if an explicitly configured monitor
            # does not belong to the instrument that owns the
            # KS level set.
            if (
                expected_security_id
                != levels.instrument_security_id
            ):
                return ()

            if tick.security_id != expected_security_id:
                return ()

            tick_date = tick.timestamp.date()

            if tick_date != levels.trading_date:
                return ()

            if self._trading_date != tick_date:
                self._trading_date = tick_date
                self._previous_price = None

            current_price = tick.ltp
            previous_price = self._previous_price

            events: list[LevelEvent] = []

            for entry_level in (
                EntryLevel.K5,
                EntryLevel.K6,
                EntryLevel.K7,
            ):
                level_name = KSLevelName(
                    entry_level.value
                )

                level_price = (
                    levels.entry_level_price(
                        entry_level
                    )
                )

                event_type = self._detect_event(
                    previous_price=previous_price,
                    current_price=current_price,
                    level_price=level_price,
                )

                if event_type is None:
                    continue

                events.append(
                    LevelEvent(
                        trading_date=tick_date,
                        instrument_security_id=(
                            levels.instrument_security_id
                        ),
                        instrument_symbol=(
                            levels.instrument_symbol
                        ),
                        level=level_name,
                        event_type=event_type,
                        level_price=level_price,
                        market_price=current_price,
                        timestamp=tick.timestamp,
                    )
                )

            self._previous_price = current_price

            return tuple(events)

    def reset(self) -> None:
        """
        Reset monitor state for a new trading session.
        """

        with self._lock:
            self._previous_price = None
            self._trading_date = None

    def _detect_event(
        self,
        previous_price: float | None,
        current_price: float,
        level_price: float,
    ) -> LevelEventType | None:
        """
        Detect one price interaction with a KS level.
        """

        tolerance = self._touch_tolerance

        lower_bound = level_price - tolerance
        upper_bound = level_price + tolerance

        if previous_price is None:
            if (
                lower_bound
                <= current_price
                <= upper_bound
            ):
                return LevelEventType.TOUCHED

            return None

        if (
            previous_price < lower_bound
            and current_price >= lower_bound
        ):
            return LevelEventType.CROSSED_UP

        if (
            previous_price > upper_bound
            and current_price <= upper_bound
        ):
            return LevelEventType.CROSSED_DOWN

        if (
            lower_bound
            <= current_price
            <= upper_bound
        ):
            return LevelEventType.TOUCHED

        return None