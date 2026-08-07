"""
Daily KS Phoenix level service.

Coordinates the completed reference candle,
base-level calculation, and K0-K7 calculation.

This service owns the current trading day's immutable KS level set.
"""

from __future__ import annotations

from datetime import date, datetime
from threading import RLock

from src.strategy.base_level_calculator import BaseLevelCalculator
from src.strategy.ks_level_calculator import KSLevelCalculator
from src.strategy.strategy_types import KSLevels, ReferenceCandle


class DailyKSLevelService:
    """
    Calculates and stores the current day's KS Phoenix levels.

    Rules:
        - One finalized KSLevels object per trading date.
        - Repeated calls for the same day return the same object.
        - A different trading date requires reset/new calculation.
        - No broker or execution logic belongs here.
    """

    def __init__(
        self,
        base_calculator: BaseLevelCalculator | None = None,
        ks_calculator: KSLevelCalculator | None = None,
    ) -> None:
        self._base_calculator = (
            base_calculator or BaseLevelCalculator()
        )

        self._ks_calculator = (
            ks_calculator or KSLevelCalculator()
        )

        self._levels: KSLevels | None = None
        self._trading_date: date | None = None

        self._lock = RLock()

    @property
    def trading_date(self) -> date | None:
        with self._lock:
            return self._trading_date

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return self._levels is not None

    def calculate(
        self,
        candle: ReferenceCandle,
        calculated_at: datetime | None = None,
    ) -> KSLevels:
        """
        Calculate the day's KS Phoenix levels.

        If levels for the same trading date already exist,
        the existing immutable object is returned.
        """

        with self._lock:
            if self._levels is not None:
                if self._trading_date == candle.trading_date:
                    return self._levels

                raise RuntimeError(
                    "KS levels already exist for another trading date; "
                    "reset service before calculating a new day"
                )

            base_levels = self._base_calculator.calculate(
                candle=candle,
                calculated_at=calculated_at,
            )

            levels = self._ks_calculator.calculate(
                candle=candle,
                base_levels=base_levels,
                calculated_at=calculated_at,
            )

            self._levels = levels
            self._trading_date = candle.trading_date

            return levels

    def get_levels(self) -> KSLevels | None:
        """
        Return today's KS level set if available.
        """

        with self._lock:
            return self._levels

    def require_levels(self) -> KSLevels:
        """
        Return today's KS levels.

        Raises RuntimeError when the levels have not yet been calculated.
        """

        with self._lock:
            if self._levels is None:
                raise RuntimeError(
                    "KS levels are not ready"
                )

            return self._levels

    def reset(self) -> None:
        """
        Clear the stored daily level set.

        Intended for the next trading session.
        """

        with self._lock:
            self._levels = None
            self._trading_date = None