"""
Phoenix M07 stop-loss policy.

Calculates a point-based stop-loss for a long option position.

Current rule:

    stop_price = actual_entry_price - risk_points

The calculated stop is rounded UP to the nearest valid tick.

Why round upward?
For a long position, a stop at 85.63 with a 0.05 tick should
become 85.65 rather than 85.60. This avoids silently increasing
the configured risk beyond the requested number of points.

This module calculates stop-loss definitions only.
It does not monitor LTP or submit exit orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    Decimal,
    ROUND_CEILING,
)
from math import isfinite

from src.risk.risk_types import (
    StopLossDefinition,
    StopLossState,
)


@dataclass(frozen=True, slots=True)
class StopLossConfig:
    """
    Configuration for point-based Phoenix stop loss.

    risk_points:
        Maximum premium-point risk from actual fill.

    tick_size:
        Valid option premium tick size.
    """

    risk_points: float = 15.0
    tick_size: float = 0.05

    def __post_init__(self) -> None:
        if not isfinite(
            self.risk_points
        ):
            raise ValueError(
                "risk_points must be finite"
            )

        if self.risk_points <= 0:
            raise ValueError(
                "risk_points must be greater than zero"
            )

        if not isfinite(
            self.tick_size
        ):
            raise ValueError(
                "tick_size must be finite"
            )

        if self.tick_size <= 0:
            raise ValueError(
                "tick_size must be greater than zero"
            )


class StopLossPolicy:
    """
    Calculates the option-premium stop price from
    actual entry fill price.
    """

    def __init__(
        self,
        config: StopLossConfig | None = None,
    ) -> None:
        self._config = (
            config
            or StopLossConfig()
        )

    @property
    def config(
        self,
    ) -> StopLossConfig:
        return self._config

    def calculate(
        self,
        *,
        entry_price: float,
    ) -> StopLossDefinition:
        """
        Calculate the configured point-based stop loss.

        Example:
            entry_price = 100.65
            risk_points = 15
            stop = 85.65
        """

        self._validate_entry_price(
            entry_price
        )

        raw_stop = (
            entry_price
            - self._config.risk_points
        )

        if raw_stop <= 0:
            raise ValueError(
                "configured risk_points produce "
                "a non-positive stop price"
            )

        stop_price = (
            self._round_up_to_tick(
                raw_stop,
                self._config.tick_size,
            )
        )

        if stop_price >= entry_price:
            raise ValueError(
                "stop_price must remain below entry_price"
            )

        actual_risk_points = (
            entry_price
            - stop_price
        )

        if actual_risk_points <= 0:
            raise ValueError(
                "calculated risk_points must be "
                "greater than zero"
            )

        return StopLossDefinition(
            stop_price=stop_price,
            risk_points=actual_risk_points,
            state=StopLossState.ARMED,
        )

    @staticmethod
    def _validate_entry_price(
        entry_price: float,
    ) -> None:
        if not isfinite(
            entry_price
        ):
            raise ValueError(
                "entry_price must be finite"
            )

        if entry_price <= 0:
            raise ValueError(
                "entry_price must be greater than zero"
            )

    @staticmethod
    def _round_up_to_tick(
        price: float,
        tick_size: float,
    ) -> float:
        """
        Round upward to the nearest valid tick.

        Examples with 0.05 tick:

            85.65 -> 85.65
            85.63 -> 85.65
            85.601 -> 85.65

        Rounding upward ensures the actual monetary risk
        never exceeds the configured point risk because
        of tick normalization.
        """

        price_decimal = Decimal(
            str(price)
        )

        tick_decimal = Decimal(
            str(tick_size)
        )

        ticks = (
            price_decimal
            / tick_decimal
        ).to_integral_value(
            rounding=ROUND_CEILING
        )

        result = (
            ticks
            * tick_decimal
        )

        return float(
            result
        )