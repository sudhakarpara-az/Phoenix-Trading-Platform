"""
Phoenix M07 underlying-to-option target mapping boundary.

This module prevents strategy underlying prices from being
mistaken for option premium prices.

Important:

    NIFTY KS target level
        !=
    option premium target

The mapper does NOT calculate theoretical option price from
underlying movement.

Instead, when the underlying target condition is reached,
Phoenix captures the current observed option premium and
records that as the mapped option target reference.

No broker execution belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from src.execution.position_exit_types import (
    FilledPositionId,
)


class OptionTargetMappingStatus(str, Enum):
    """
    Outcome of one target mapping attempt.
    """

    MAPPED = "MAPPED"

    UNDERLYING_NOT_REACHED = (
        "UNDERLYING_NOT_REACHED"
    )

    OPTION_PRICE_NOT_AVAILABLE = (
        "OPTION_PRICE_NOT_AVAILABLE"
    )


class UnderlyingTargetDirection(str, Enum):
    """
    Direction used to determine whether the underlying
    target has been reached.

    ABOVE_OR_EQUAL:
        target condition:
            current_underlying >= target_underlying

    BELOW_OR_EQUAL:
        target condition:
            current_underlying <= target_underlying
    """

    ABOVE_OR_EQUAL = "ABOVE_OR_EQUAL"

    BELOW_OR_EQUAL = "BELOW_OR_EQUAL"


@dataclass(frozen=True, slots=True)
class UnderlyingTarget:
    """
    Strategy-domain target.

    target_price is always an UNDERLYING NIFTY price.

    It must never be passed directly into M06 option-premium
    target calculation.
    """

    target_price: float

    direction: UnderlyingTargetDirection

    level_name: str

    def __post_init__(self) -> None:
        if not isfinite(
            self.target_price
        ):
            raise ValueError(
                "underlying target price must be finite"
            )

        if self.target_price <= 0:
            raise ValueError(
                "underlying target price must be "
                "greater than zero"
            )

        if not self.level_name.strip():
            raise ValueError(
                "level_name cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class OptionTargetMapping:
    """
    Typed boundary result connecting the strategy domain
    to the option-premium domain.

    underlying_target_price:
        NIFTY target level.

    underlying_price_at_mapping:
        Actual NIFTY price when target condition was evaluated.

    option_price_at_mapping:
        Observed option LTP at the same mapping event.

    mapped_option_target_price:
        Option premium that downstream M06 target logic may use.
    """

    position_id: FilledPositionId

    underlying_target_price: float

    underlying_price_at_mapping: float

    option_price_at_mapping: float

    mapped_option_target_price: float

    mapped_at: datetime

    level_name: str

    def __post_init__(self) -> None:
        values = {
            "underlying_target_price": (
                self.underlying_target_price
            ),
            "underlying_price_at_mapping": (
                self.underlying_price_at_mapping
            ),
            "option_price_at_mapping": (
                self.option_price_at_mapping
            ),
            "mapped_option_target_price": (
                self.mapped_option_target_price
            ),
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

        if not self.level_name.strip():
            raise ValueError(
                "level_name cannot be empty"
            )

        if (
            self.mapped_option_target_price
            != self.option_price_at_mapping
        ):
            raise ValueError(
                "mapped_option_target_price must equal "
                "observed option price at mapping"
            )


@dataclass(frozen=True, slots=True)
class OptionTargetMappingResult:
    status: OptionTargetMappingStatus

    mapping: OptionTargetMapping | None

    underlying_price: float

    option_ltp: float | None

    evaluated_at: datetime

    @property
    def mapped(self) -> bool:
        return (
            self.status
            is OptionTargetMappingStatus.MAPPED
            and self.mapping is not None
        )


class OptionTargetMapper:
    """
    Explicit boundary between:

        strategy underlying target
            and
        option premium target.

    The mapper does not infer theoretical option value.

    It only maps when:
        1. underlying target condition is reached
        2. a valid current option LTP is available
    """

    def map_target(
        self,
        *,
        position_id: FilledPositionId,
        target: UnderlyingTarget,
        current_underlying_price: float,
        current_option_ltp: float | None,
        evaluated_at: datetime,
    ) -> OptionTargetMappingResult:
        self._validate_underlying_price(
            current_underlying_price
        )

        reached = self._is_target_reached(
            current_price=(
                current_underlying_price
            ),
            target=target,
        )

        if not reached:
            return OptionTargetMappingResult(
                status=(
                    OptionTargetMappingStatus
                    .UNDERLYING_NOT_REACHED
                ),
                mapping=None,
                underlying_price=(
                    current_underlying_price
                ),
                option_ltp=current_option_ltp,
                evaluated_at=evaluated_at,
            )

        if current_option_ltp is None:
            return OptionTargetMappingResult(
                status=(
                    OptionTargetMappingStatus
                    .OPTION_PRICE_NOT_AVAILABLE
                ),
                mapping=None,
                underlying_price=(
                    current_underlying_price
                ),
                option_ltp=None,
                evaluated_at=evaluated_at,
            )

        self._validate_option_price(
            current_option_ltp
        )

        mapping = OptionTargetMapping(
            position_id=position_id,
            underlying_target_price=(
                target.target_price
            ),
            underlying_price_at_mapping=(
                current_underlying_price
            ),
            option_price_at_mapping=(
                current_option_ltp
            ),
            mapped_option_target_price=(
                current_option_ltp
            ),
            mapped_at=evaluated_at,
            level_name=target.level_name,
        )

        return OptionTargetMappingResult(
            status=(
                OptionTargetMappingStatus.MAPPED
            ),
            mapping=mapping,
            underlying_price=(
                current_underlying_price
            ),
            option_ltp=current_option_ltp,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _is_target_reached(
        *,
        current_price: float,
        target: UnderlyingTarget,
    ) -> bool:
        if (
            target.direction
            is UnderlyingTargetDirection
            .ABOVE_OR_EQUAL
        ):
            return (
                current_price
                >= target.target_price
            )

        if (
            target.direction
            is UnderlyingTargetDirection
            .BELOW_OR_EQUAL
        ):
            return (
                current_price
                <= target.target_price
            )

        raise ValueError(
            "unsupported underlying target direction"
        )

    @staticmethod
    def _validate_underlying_price(
        value: float,
    ) -> None:
        if not isfinite(value):
            raise ValueError(
                "current underlying price must be finite"
            )

        if value <= 0:
            raise ValueError(
                "current underlying price must be "
                "greater than zero"
            )

    @staticmethod
    def _validate_option_price(
        value: float,
    ) -> None:
        if not isfinite(value):
            raise ValueError(
                "current option LTP must be finite"
            )

        if value <= 0:
            raise ValueError(
                "current option LTP must be "
                "greater than zero"
            )