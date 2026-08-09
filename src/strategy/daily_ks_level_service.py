"""
Daily KS Phoenix level service.

Coordinates the completed reference candle,
base-level calculation, and K0-K7 calculation.

Each service instance owns one immutable KS level set for
one trading date and one strategy instrument.
"""

from __future__ import annotations

from datetime import date, datetime
from threading import RLock

from src.strategy.base_level_calculator import (
    BaseLevelCalculator,
)
from src.strategy.ks_level_calculator import (
    KSLevelCalculator,
)
from src.strategy.strategy_types import (
    KSLevels,
    ReferenceCandle,
)


class DailyKSLevelService:
    """
    Calculates and stores one strategy instrument's
    KS Phoenix levels.

    Rules:
        - One finalized KSLevels object per service instance.
        - The level set belongs to one trading date.
        - The level set belongs to one strategy instrument.
        - Repeated calls for the same date and instrument
          return the same immutable object.
        - A different date requires reset/new calculation.
        - A different instrument requires reset or a separate
          service instance.
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
        Calculate the strategy instrument's KS Phoenix levels.

        If levels for the same trading date and instrument
        already exist, the existing immutable object is returned.

        A different date or instrument must not silently reuse
        the existing level set.
        """

        with self._lock:
            if self._levels is not None:
                if self._trading_date != candle.trading_date:
                    raise RuntimeError(
                        "KS levels already exist for another "
                        "trading date; reset service before "
                        "calculating a new day"
                    )

                if (
                    self._levels.instrument_security_id
                    != candle.instrument_security_id
                    or self._levels.instrument_symbol
                    != candle.instrument_symbol
                ):
                    raise RuntimeError(
                        "KS levels already exist for another "
                        "instrument; reset service before "
                        "calculating another instrument"
                    )

                return self._levels

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
        Return the stored KS level set if available.
        """

        with self._lock:
            return self._levels

    def require_levels(self) -> KSLevels:
        """
        Return the stored KS level set.

        Raises RuntimeError when levels have not yet
        been calculated.
        """

        with self._lock:
            if self._levels is None:
                raise RuntimeError(
                    "KS levels are not ready"
                )

            return self._levels

    def reset(self) -> None:
        """
        Clear the stored level set.

        After reset, the service may calculate levels for
        another trading date or another strategy instrument.
        """

        with self._lock:
            self._levels = None
            self._trading_date = None