"""
Phoenix order pricing policy.

Calculates broker-independent LIMIT BUY prices from
the selected option LTP using a configurable positive
entry buffer and exchange tick-size rounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from math import isfinite

from src.option_selection.option_types import SelectedOption


@dataclass(frozen=True, slots=True)
class OrderPricingConfig:
    """
    Configuration for Phoenix LIMIT BUY pricing.

    Current Phoenix rule:
        option LTP + 1 to 2 point buffer

    Default:
        buffer = 1.0
        tick_size = 0.05
    """

    entry_buffer_points: float = 1.0
    tick_size: float = 0.05

    def __post_init__(self) -> None:
        if not isfinite(self.entry_buffer_points):
            raise ValueError(
                "entry_buffer_points must be a finite number"
            )

        if not 1.0 <= self.entry_buffer_points <= 2.0:
            raise ValueError(
                "entry_buffer_points must be between 1 and 2"
            )

        if not isfinite(self.tick_size):
            raise ValueError(
                "tick_size must be a finite number"
            )

        if self.tick_size <= 0:
            raise ValueError(
                "tick_size must be greater than zero"
            )


@dataclass(frozen=True, slots=True)
class OrderPrice:
    """
    Result of Phoenix order-price calculation.
    """

    reference_ltp: float
    buffer_points: float
    raw_price: float
    limit_price: float
    tick_size: float


class OrderPricingPolicy:
    """
    Calculates LIMIT BUY price for a SelectedOption.

    Processing:

        SelectedOption.ltp
            +
        configured entry buffer
            ↓
        raw intended price
            ↓
        round UP to valid tick
            ↓
        LIMIT BUY price
    """

    def __init__(
        self,
        config: OrderPricingConfig | None = None,
    ) -> None:
        self._config = (
            config or OrderPricingConfig()
        )

    @property
    def config(self) -> OrderPricingConfig:
        return self._config

    def calculate(
        self,
        selected_option: SelectedOption,
    ) -> OrderPrice:
        """
        Calculate Phoenix LIMIT BUY price.
        """

        ltp = selected_option.ltp

        if not isfinite(ltp):
            raise ValueError(
                "selected option LTP must be finite"
            )

        if ltp <= 0:
            raise ValueError(
                "selected option LTP must be greater than zero"
            )

        raw_price = (
            ltp
            + self._config.entry_buffer_points
        )

        limit_price = self._round_up_to_tick(
            price=raw_price,
            tick_size=self._config.tick_size,
        )

        return OrderPrice(
            reference_ltp=ltp,
            buffer_points=(
                self._config.entry_buffer_points
            ),
            raw_price=raw_price,
            limit_price=limit_price,
            tick_size=self._config.tick_size,
        )

    @staticmethod
    def _round_up_to_tick(
        price: float,
        tick_size: float,
    ) -> float:
        """
        Round price upward to the nearest valid exchange tick.

        Decimal arithmetic avoids floating-point artifacts.

        Example with tick_size=0.05:

            101.01 -> 101.05
            101.05 -> 101.05
            101.06 -> 101.10
        """

        price_decimal = Decimal(str(price))
        tick_decimal = Decimal(str(tick_size))

        tick_count = (
            price_decimal / tick_decimal
        ).to_integral_value(
            rounding=ROUND_CEILING
        )

        rounded = (
            tick_count
            * tick_decimal
        )

        return float(rounded)