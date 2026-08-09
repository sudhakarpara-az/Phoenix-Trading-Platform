"""
KS Phoenix K0-K7 calculator.

Implements the finalized KS Phoenix Pine Script formulas,
including the intentional K0/K1 label swap.
"""

from __future__ import annotations

from datetime import datetime

from src.strategy.strategy_types import (
    KSBaseLevels,
    KSLevels,
    ReferenceCandle,
)


class KSLevelCalculator:
    """
    Calculates the complete KS Phoenix level set.

    The calculated level set belongs to the same strategy
    instrument as the reference candle and base levels.

    Pine logic:

        ks0_calculated_value = n2 * 0.118 / 0.5
        ks_k1_calculated_value = n1 * 0.786 / 0.5

        K0 = ks_k1_calculated_value
        K1 = ks0_calculated_value

        K2 = ks0 + 0.763 * (ks_k1 - ks0)
        K3 = ks0 + 0.618 * (ks_k1 - ks0)
        K5 = ks0 + 0.500 * (ks_k1 - ks0)
        K6 = ks0 + 0.382 * (ks_k1 - ks0)
        K7 = ks0 + 0.220 * (ks_k1 - ks0)
    """

    KS0_FACTOR = 0.118
    KS1_FACTOR = 0.786
    DIVISOR = 0.5

    K2_RATIO = 0.763
    K3_RATIO = 0.618
    K5_RATIO = 0.500
    K6_RATIO = 0.382
    K7_RATIO = 0.220

    FORMULA_VERSION = "KS_PHOENIX_V1"

    def calculate(
        self,
        candle: ReferenceCandle,
        base_levels: KSBaseLevels,
        calculated_at: datetime | None = None,
    ) -> KSLevels:
        """
        Calculate the complete KS level set.

        The reference candle and base levels must belong
        to the same trading date and strategy instrument.
        """

        if candle.trading_date != base_levels.trading_date:
            raise ValueError(
                "candle and base_levels trading_date must match"
            )

        if (
            candle.instrument_security_id
            != base_levels.instrument_security_id
        ):
            raise ValueError(
                "candle and base_levels "
                "instrument_security_id must match"
            )

        if (
            candle.instrument_symbol
            != base_levels.instrument_symbol
        ):
            raise ValueError(
                "candle and base_levels "
                "instrument_symbol must match"
            )

        n1 = base_levels.n1
        n2 = base_levels.n2

        ks0_calculated_value = (
            n2 * self.KS0_FACTOR / self.DIVISOR
        )

        ks_k1_calculated_value = (
            n1 * self.KS1_FACTOR / self.DIVISOR
        )

        # Finalized Pine behavior:
        #
        # displayed K0 uses ks_k1_calculated_value
        # displayed K1 uses ks0_calculated_value
        k0 = ks_k1_calculated_value
        k1 = ks0_calculated_value

        ks_range = (
            ks_k1_calculated_value
            - ks0_calculated_value
        )

        k2 = (
            ks0_calculated_value
            + self.K2_RATIO * ks_range
        )

        k3 = (
            ks0_calculated_value
            + self.K3_RATIO * ks_range
        )

        k5 = (
            ks0_calculated_value
            + self.K5_RATIO * ks_range
        )

        k6 = (
            ks0_calculated_value
            + self.K6_RATIO * ks_range
        )

        k7 = (
            ks0_calculated_value
            + self.K7_RATIO * ks_range
        )

        return KSLevels(
            trading_date=candle.trading_date,
            instrument_security_id=(
                candle.instrument_security_id
            ),
            instrument_symbol=candle.instrument_symbol,

            high_915=candle.high,
            low_915=candle.low,
            close_915=candle.close,

            n1=base_levels.n1,
            n2=base_levels.n2,
            c1=base_levels.c1,

            e_level=base_levels.e_level,
            t_level=base_levels.t_level,

            k0=k0,
            k1=k1,
            k2=k2,
            k3=k3,
            k5=k5,
            k6=k6,
            k7=k7,

            calculated_at=calculated_at or datetime.now(),
            formula_version=self.FORMULA_VERSION,
        )