"""
Phoenix M07 option-contract KS target mapping boundary.

The strategy instrument is the selected option contract itself.

Target ownership:

    FilledPosition
        +
    same-contract KSLevels
        ->
    mapped option KS target
        ->
    TargetBookingPolicy
        ->
    TargetDefinition

Current Phoenix mappings are owned by KSLevels:

    K5 -> K3
    K6 -> K5
    K7 -> K6

Important:

    - NIFTY spot is not used to derive the option target.
    - Current option LTP is not sampled to invent a target.
    - The KS target must belong to the same selected contract.
    - Target booking uses the actual broker fill price.
    - No broker execution belongs in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from src.execution.position_exit_types import (
    FilledPosition,
    FilledPositionId,
)
from src.execution.target_booking_policy import (
    TargetBookingPolicy,
)
from src.risk.risk_types import (
    TargetDefinition,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    KSLevels,
)


class OptionTargetMappingStatus(str, Enum):
    """
    Outcome of an option target mapping operation.

    UNDERLYING_NOT_REACHED and OPTION_PRICE_NOT_AVAILABLE are
    retained only as legacy enum values for import compatibility.
    The corrected option-contract mapper never returns them.
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
    Legacy target-direction type retained for import compatibility.

    The corrected OptionTargetMapper does not consume underlying
    target directions because selected-option KS levels are already
    expressed directly in option-premium prices.
    """

    ABOVE_OR_EQUAL = "ABOVE_OR_EQUAL"
    BELOW_OR_EQUAL = "BELOW_OR_EQUAL"


@dataclass(frozen=True, slots=True)
class UnderlyingTarget:
    """
    Legacy underlying-target value object.

    Retained only for compatibility with older imports.

    It is not accepted by the corrected OptionTargetMapper.
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
    Immutable same-contract KS target mapping.

    mapped_option_target_price:
        The selected option contract's own mapped KS target price.

    target_definition:
        Runtime M07 target after TargetBookingPolicy applies the
        +30 / three-point-buffer rule from actual broker fill.
    """

    position_id: FilledPositionId

    instrument_security_id: str
    instrument_symbol: str

    entry_level: EntryLevel
    target_level: KSLevelName

    mapped_option_target_price: float

    target_definition: TargetDefinition

    mapped_at: datetime

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )

        if not self.instrument_symbol.strip():
            raise ValueError(
                "instrument_symbol cannot be empty"
            )

        if not isfinite(
            self.mapped_option_target_price
        ):
            raise ValueError(
                "mapped_option_target_price must be finite"
            )

        if self.mapped_option_target_price <= 0:
            raise ValueError(
                "mapped_option_target_price must be "
                "greater than zero"
            )

        if (
            self.target_definition
            .mapped_target_price
            != self.mapped_option_target_price
        ):
            raise ValueError(
                "target definition mapped price must match "
                "mapped option target price"
            )


@dataclass(frozen=True, slots=True)
class OptionTargetMappingResult:
    """
    Successful same-contract option target mapping result.

    Invalid ownership or invalid target arithmetic fails closed by
    raising before a result is produced.
    """

    status: OptionTargetMappingStatus
    mapping: OptionTargetMapping

    @property
    def mapped(self) -> bool:
        return (
            self.status
            is OptionTargetMappingStatus.MAPPED
        )


class OptionTargetMapper:
    """
    Maps one filled option position to its own KS target.

    The supplied KSLevels must belong to the exact same:
        - trading date
        - security ID
        - symbol

    Target price resolution is:

        position.level
            ->
        levels.target_for(...)
            ->
        levels.get(...)
            ->
        TargetBookingPolicy
    """

    def __init__(
        self,
        target_booking_policy: TargetBookingPolicy | None = None,
    ) -> None:
        self._target_booking_policy = (
            target_booking_policy
            or TargetBookingPolicy()
        )

    @property
    def target_booking_policy(
        self,
    ) -> TargetBookingPolicy:
        return self._target_booking_policy

    def map_target(
        self,
        *,
        position: FilledPosition,
        levels: KSLevels,
        mapped_at: datetime,
    ) -> OptionTargetMappingResult:
        """
        Build the runtime target for one filled option position.

        No current underlying price or current option LTP is needed.
        The target is already present in the selected contract's
        finalized KSLevels.
        """

        self._validate_ownership(
            position=position,
            levels=levels,
        )

        if mapped_at < position.filled_at:
            raise ValueError(
                "mapped_at cannot be before position filled_at"
            )

        target_level = levels.target_for(
            position.level
        )

        mapped_target_price = levels.get(
            target_level
        )

        target_plan = (
            self._target_booking_policy.calculate(
                entry_price=position.entry_price,
                mapped_target_price=(
                    mapped_target_price
                ),
            )
        )

        target_definition = TargetDefinition(
            executable_price=(
                target_plan
                .executable_target_price
            ),
            mapped_target_price=(
                target_plan
                .mapped_target_price
            ),
            booking_zone_start=(
                target_plan
                .booking_zone_start
            ),
            booking_zone_end=(
                target_plan
                .booking_zone_end
            ),
        )

        mapping = OptionTargetMapping(
            position_id=position.position_id,
            instrument_security_id=(
                position.security_id
            ),
            instrument_symbol=position.symbol,
            entry_level=position.level,
            target_level=target_level,
            mapped_option_target_price=(
                mapped_target_price
            ),
            target_definition=(
                target_definition
            ),
            mapped_at=mapped_at,
        )

        return OptionTargetMappingResult(
            status=(
                OptionTargetMappingStatus.MAPPED
            ),
            mapping=mapping,
        )

    @staticmethod
    def _validate_ownership(
        *,
        position: FilledPosition,
        levels: KSLevels,
    ) -> None:
        if (
            levels.instrument_security_id
            != position.security_id
        ):
            raise ValueError(
                "KS levels security ID does not match "
                "filled position security ID"
            )

        if (
            levels.instrument_symbol
            != position.symbol
        ):
            raise ValueError(
                "KS levels symbol does not match "
                "filled position symbol"
            )

        if (
            levels.trading_date
            != position.filled_at.date()
        ):
            raise ValueError(
                "KS levels trading date does not match "
                "filled position trading date"
            )
