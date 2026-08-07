"""
Phoenix execution quantity / lot-size validation.

Ensures broker order quantities are positive whole multiples
of the selected option contract's lot size.

No broker-specific order placement belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.option_selection.option_types import SelectedOption


@dataclass(frozen=True, slots=True)
class QuantityValidationResult:
    """
    Result of quantity validation.
    """

    valid: bool

    requested_quantity: int
    lot_size: int

    lot_count: int | None = None
    message: str | None = None


class QuantityPolicy:
    """
    Validates execution quantity against option lot size.

    Rules:
        - Quantity must be greater than zero.
        - Contract lot size must be greater than zero.
        - Quantity must be an exact multiple of lot size.
    """

    def validate(
        self,
        selected_option: SelectedOption,
        quantity: int,
    ) -> QuantityValidationResult:
        """
        Validate requested execution quantity.
        """

        lot_size = selected_option.lot_size

        if lot_size <= 0:
            return QuantityValidationResult(
                valid=False,
                requested_quantity=quantity,
                lot_size=lot_size,
                message="selected option lot size is invalid",
            )

        if quantity <= 0:
            return QuantityValidationResult(
                valid=False,
                requested_quantity=quantity,
                lot_size=lot_size,
                message="quantity must be greater than zero",
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

        lot_count = quantity // lot_size

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