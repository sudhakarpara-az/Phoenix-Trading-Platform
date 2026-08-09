"""
KS Phoenix N1/N2/C1/E/T calculator.

Implements the base calculations from the finalized
KS Phoenix Pine Script.

This module does not calculate K0-K7.
"""

from __future__ import annotations

import math
from datetime import datetime

from src.strategy.strategy_types import (
    KSBaseLevels,
    ReferenceCandle,
)


class BaseLevelCalculator:
    """
    Calculates the intermediate KS Phoenix levels:

        N1
        N2
        C1
        E
        T

    using the completed strategy-instrument reference candle.
    """

    E_FACTOR = 3.2
    T_FACTOR = 7.1
    FACTOR_DIVISOR = 1000.0

    def calculate(
        self,
        candle: ReferenceCandle,
        calculated_at: datetime | None = None,
    ) -> KSBaseLevels:
        """
        Calculate N1, N2, C1, E and T.

        Pine-equivalent formulas:

            diff = high915 - low915
            result = diff / 2

            n1 = high915 + result
            n2 = low915 + result

            c1 = (n1 + n2) / 2

            e = n2 - floor(n2 * 3.2 / 1000)
            t = n2 + floor(n2 * 7.1 / 1000)
        """

        high_915 = candle.high
        low_915 = candle.low

        price_range = high_915 - low_915
        half_range = price_range / 2.0

        n1 = high_915 + half_range
        n2 = low_915 + half_range

        c1 = (n1 + n2) / 2.0

        e_adjustment = math.floor(
            n2 * self.E_FACTOR / self.FACTOR_DIVISOR
        )

        t_adjustment = math.floor(
            n2 * self.T_FACTOR / self.FACTOR_DIVISOR
        )

        e_level = n2 - e_adjustment
        t_level = n2 + t_adjustment

        return KSBaseLevels(
            trading_date=candle.trading_date,
            instrument_security_id=(
                candle.instrument_security_id
            ),
            instrument_symbol=candle.instrument_symbol,
            n1=n1,
            n2=n2,
            c1=c1,
            e_level=e_level,
            t_level=t_level,
            calculated_at=calculated_at or datetime.now(),
        )