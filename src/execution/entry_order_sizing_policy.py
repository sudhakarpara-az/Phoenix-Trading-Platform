"""
Phoenix entry-order sizing policy.

Combines existing execution-domain policies to determine the
complete economic size of one proposed LIMIT BUY entry.

Flow:

    preferred_lots
        *
    selected option contract lot_size
        ->
    requested_quantity

    selected option LTP
        +
    configured entry buffer
        ->
    executable LIMIT BUY price

    requested_quantity
        *
    executable LIMIT BUY price
        ->
    required_cash

This module does not:
    - read account preferences
    - check available funds
    - enforce M07 exposure limits
    - place broker orders
    - silently reduce requested quantity
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.execution.order_pricing_policy import (
    OrderPrice,
    OrderPricingPolicy,
)
from src.execution.quantity_policy import (
    QuantityCalculation,
    QuantityPolicy,
)
from src.option_selection.option_types import (
    SelectedOption,
)


@dataclass(frozen=True, slots=True)
class EntryOrderSizing:
    """
    Immutable economic sizing for one proposed option BUY.
    """

    preferred_lots: int

    lot_size: int

    requested_quantity: int

    pricing: OrderPrice

    required_cash: Decimal


class EntryOrderSizingPolicy:
    """
    Resolve quantity, buffered LIMIT price and required cash.

    No account or broker limit may silently downsize the result.
    Downstream gates either accept the full requested quantity
    or block the entry.
    """

    def __init__(
        self,
        *,
        quantity_policy: QuantityPolicy | None = None,
        pricing_policy: OrderPricingPolicy | None = None,
    ) -> None:
        self._quantity_policy = (
            quantity_policy
            or QuantityPolicy()
        )

        self._pricing_policy = (
            pricing_policy
            or OrderPricingPolicy()
        )

    @property
    def quantity_policy(
        self,
    ) -> QuantityPolicy:
        return self._quantity_policy

    @property
    def pricing_policy(
        self,
    ) -> OrderPricingPolicy:
        return self._pricing_policy

    def calculate(
        self,
        *,
        selected_option: SelectedOption,
        preferred_lots: int = 1,
    ) -> EntryOrderSizing:
        """
        Calculate complete sizing for one proposed entry.
        """

        quantity: QuantityCalculation = (
            self._quantity_policy
            .calculate_from_lots(
                selected_option=selected_option,
                preferred_lots=preferred_lots,
            )
        )

        pricing = (
            self._pricing_policy
            .calculate(
                selected_option
            )
        )

        required_cash = (
            Decimal(
                str(pricing.limit_price)
            )
            * Decimal(
                quantity.requested_quantity
            )
        )

        if required_cash <= Decimal("0"):
            raise ValueError(
                "required_cash must be greater than zero"
            )

        return EntryOrderSizing(
            preferred_lots=(
                quantity.preferred_lots
            ),
            lot_size=quantity.lot_size,
            requested_quantity=(
                quantity.requested_quantity
            ),
            pricing=pricing,
            required_cash=required_cash,
        )
