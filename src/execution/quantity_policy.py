"""
Phoenix execution quantity / lot-size policy.

Responsibilities:
    - Calculate requested execution quantity from a preferred
      number of lots and the selected option contract lot size.
    - Validate absolute broker order quantities.
    - Never hardcode a NIFTY lot size.
    - Never silently reduce a requested lot count.

No broker-specific order placement, account persistence,
funds eligibility or exposure-limit logic belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.option_selection.option_types import (
    SelectedOption,
)


@dataclass(frozen=True, slots=True)
class QuantityCalculation:
    """
    Immutable quantity calculation for one selected contract.

    requested_quantity is always:

        preferred_lots * selected contract lot_size
    """

    preferred_lots: int

    lot_size: int

    requested_quantity: int


@dataclass(frozen=True, slots=True)
class QuantityValidationResult:
    """
    Result of absolute execution-quantity validation.
    """

    valid: bool

    requested_quantity: int

    lot_size: int

    lot_count: int | None = None

    message: str | None = None


class QuantityPolicy:
    """
    Phoenix execution quantity policy.

    Calculation rule:

        preferred_lots
            *
        selected_option.lot_size
            =
        requested_quantity

    Validation rules:
        - Quantity must be greater than zero.
        - Contract lot size must be greater than zero.
        - Quantity must be an exact multiple of lot size.

    This policy deliberately has no maximum-lot setting.
    Account/risk/broker limits must block the complete requested
    quantity rather than silently downsizing it.
    """

    def calculate_from_lots(
        self,
        selected_option: SelectedOption,
        preferred_lots: int = 1,
    ) -> QuantityCalculation:
        """
        Calculate absolute quantity from preferred lot count.

        The default preference is one lot.

        Raises:
            ValueError:
                when preferred_lots is not a positive integer or
                the selected contract exposes an invalid lot size.
        """

        if (
            isinstance(preferred_lots, bool)
            or not isinstance(
                preferred_lots,
                int,
            )
        ):
            raise ValueError(
                "preferred_lots must be an integer"
            )

        if preferred_lots <= 0:
            raise ValueError(
                "preferred_lots must be greater than zero"
            )

        lot_size = selected_option.lot_size

        if lot_size <= 0:
            raise ValueError(
                "selected option lot size is invalid"
            )

        requested_quantity = (
            preferred_lots
            * lot_size
        )

        # Preserve one authoritative validation path for broker
        # quantities even though multiplication above naturally
        # produces a whole-lot quantity.
        self.require_valid(
            selected_option=selected_option,
            quantity=requested_quantity,
        )

        return QuantityCalculation(
            preferred_lots=preferred_lots,
            lot_size=lot_size,
            requested_quantity=(
                requested_quantity
            ),
        )

    def validate(
        self,
        selected_option: SelectedOption,
        quantity: int,
    ) -> QuantityValidationResult:
        """
        Validate requested absolute execution quantity.
        """

        lot_size = selected_option.lot_size

        if lot_size <= 0:
            return QuantityValidationResult(
                valid=False,
                requested_quantity=quantity,
                lot_size=lot_size,
                message=(
                    "selected option lot size is invalid"
                ),
            )

        if quantity <= 0:
            return QuantityValidationResult(
                valid=False,
                requested_quantity=quantity,
                lot_size=lot_size,
                message=(
                    "quantity must be greater than zero"
                ),
            )

        if quantity % lot_size != 0:
            return QuantityValidationResult(
                valid=False,
                requested_quantity=quantity,
                lot_size=lot_size,
                message=(
                    "quantity must be an exact multiple "
                    "of option lot size"
                ),
            )

        lot_count = (
            quantity
            // lot_size
        )

        return QuantityValidationResult(
            valid=True,
            requested_quantity=quantity,
            lot_size=lot_size,
            lot_count=lot_count,
        )

    def require_valid(
        self,
        selected_option: SelectedOption,
        quantity: int,
    ) -> int:
        """
        Validate quantity and return number of lots.

        Raises:
            ValueError when quantity is invalid.
        """

        result = self.validate(
            selected_option=selected_option,
            quantity=quantity,
        )

        if not result.valid:
            raise ValueError(
                result.message
                or "invalid execution quantity"
            )

        assert result.lot_count is not None

        return result.lot_count
