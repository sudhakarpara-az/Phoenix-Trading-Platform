"""
Phoenix target booking policy.

Calculates the profit-booking target for an already filled
long option position.

Current Phoenix rule:

1. If the mapped KS target is more than 30 option-price
   points above the actual entry price:

       target = entry + 30

2. If the mapped KS target is 30 points or less above entry:

       booking trigger = mapped KS target - 3 points

   The area between the buffered trigger and the original
   KS target is retained as the booking zone.

This module calculates target prices only.
It does not place broker exit orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    Decimal,
    ROUND_FLOOR,
)
from enum import Enum
from math import isfinite


class TargetBookingMode(str, Enum):
    """
    Reason used to derive the executable target.
    """

    FIXED_30_POINTS = "FIXED_30_POINTS"

    NEAR_KS_TARGET = "NEAR_KS_TARGET"


@dataclass(frozen=True, slots=True)
class TargetBookingConfig:
    """
    Phoenix target configuration.
    """

    max_profit_points: float = 30.0

    ks_target_buffer_points: float = 3.0

    tick_size: float = 0.05

    def __post_init__(self) -> None:
        values = {
            "max_profit_points": (
                self.max_profit_points
            ),
            "ks_target_buffer_points": (
                self.ks_target_buffer_points
            ),
            "tick_size": self.tick_size,
        }

        for name, value in values.items():
            if not isfinite(value):
                raise ValueError(
                    f"{name} must be finite"
                )

            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )

        if (
            self.ks_target_buffer_points
            >= self.max_profit_points
        ):
            raise ValueError(
                "ks_target_buffer_points must be "
                "less than max_profit_points"
            )


@dataclass(frozen=True, slots=True)
class TargetBookingPlan:
    """
    Immutable profit-booking plan.

    mapped_target_price:
        Original mapped KS target.

    target_distance_points:
        Distance from actual fill to mapped KS target.

    executable_target_price:
        Price at which Phoenix begins profit booking.

    booking_zone_start:
        Beginning of the booking zone.

    booking_zone_end:
        Original KS target / end of booking zone.

    mode:
        Fixed +30 or buffered nearby KS target.
    """

    entry_price: float

    mapped_target_price: float

    target_distance_points: float

    executable_target_price: float

    booking_zone_start: float

    booking_zone_end: float

    mode: TargetBookingMode

    tick_size: float


class TargetBookingPolicy:
    """
    Calculates Phoenix option-buying profit targets.
    """

    def __init__(
        self,
        config: TargetBookingConfig | None = None,
    ) -> None:
        self._config = (
            config
            or TargetBookingConfig()
        )

    @property
    def config(
        self,
    ) -> TargetBookingConfig:
        return self._config

    def calculate(
        self,
        *,
        entry_price: float,
        mapped_target_price: float,
    ) -> TargetBookingPlan:
        """
        Calculate the executable target from actual fill price
        and mapped KS target price.
        """

        self._validate_price(
            entry_price,
            "entry_price",
        )

        self._validate_price(
            mapped_target_price,
            "mapped_target_price",
        )

        if mapped_target_price <= entry_price:
            raise ValueError(
                "mapped_target_price must be above entry_price"
            )

        distance = (
            mapped_target_price
            - entry_price
        )

        # --------------------------------------------------
        # Target farther than 30 points
        # --------------------------------------------------

        if (
            distance
            > self._config.max_profit_points
        ):
            raw_target = (
                entry_price
                + self._config.max_profit_points
            )

            executable = (
                self._round_down_to_tick(
                    raw_target,
                    self._config.tick_size,
                )
            )

            return TargetBookingPlan(
                entry_price=entry_price,
                mapped_target_price=mapped_target_price,
                target_distance_points=distance,
                executable_target_price=executable,
                booking_zone_start=executable,
                booking_zone_end=executable,
                mode=(
                    TargetBookingMode
                    .FIXED_30_POINTS
                ),
                tick_size=self._config.tick_size,
            )

        # --------------------------------------------------
        # Nearby KS target
        # --------------------------------------------------

        raw_buffered_target = (
            mapped_target_price
            - self._config.ks_target_buffer_points
        )

        # If the KS target is too close to entry, subtracting
        # three points would create a target at/below entry.
        # Fail closed instead of producing a non-profitable exit.
        if raw_buffered_target <= entry_price:
            raise ValueError(
                "mapped target is too close to entry "
                "for configured KS target buffer"
            )

        executable = (
            self._round_down_to_tick(
                raw_buffered_target,
                self._config.tick_size,
            )
        )

        if executable <= entry_price:
            raise ValueError(
                "buffered executable target must be above entry_price"
            )

        booking_zone_end = (
            self._round_down_to_tick(
                mapped_target_price,
                self._config.tick_size,
            )
        )

        return TargetBookingPlan(
            entry_price=entry_price,
            mapped_target_price=mapped_target_price,
            target_distance_points=distance,
            executable_target_price=executable,
            booking_zone_start=executable,
            booking_zone_end=booking_zone_end,
            mode=(
                TargetBookingMode
                .NEAR_KS_TARGET
            ),
            tick_size=self._config.tick_size,
        )

    @staticmethod
    def _validate_price(
        value: float,
        name: str,
    ) -> None:
        if not isfinite(value):
            raise ValueError(
                f"{name} must be finite"
            )

        if value <= 0:
            raise ValueError(
                f"{name} must be greater than zero"
            )

    @staticmethod
    def _round_down_to_tick(
        price: float,
        tick_size: float,
    ) -> float:
        """
        Round target downward to a valid tick.

        For profit booking we don't want tick rounding to push
        the trigger farther away from the market.

        Example:
            126.03 with 0.05 tick -> 126.00
            126.05 with 0.05 tick -> 126.05
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
            rounding=ROUND_FLOOR
        )

        result = (
            ticks
            * tick_decimal
        )

        return float(
            result
        )