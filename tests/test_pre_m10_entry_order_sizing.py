from datetime import (
    date,
    datetime,
)
from decimal import Decimal

import pytest

from src.execution.entry_order_sizing_policy import (
    EntryOrderSizingPolicy,
)
from src.execution.order_pricing_policy import (
    OrderPricingConfig,
    OrderPricingPolicy,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)


EXPIRY = date(
    2026,
    8,
    11,
)

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


def make_selected_option(
    *,
    lot_size: int,
    ltp: float,
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-"
                    "24450-CE"
                ),
                security_id="41009",
                option_type=OptionType.CALL,
                strike=24450.0,
                expiry=EXPIRY,
                lot_size=lot_size,
            ),
            quote=OptionQuote(
                ltp=ltp,
                bid=ltp - 0.10,
                ask=ltp + 0.10,
                volume=1000,
                open_interest=50000,
                received_at=NOW,
            ),
            greeks=OptionGreeks(
                delta=0.60,
                calculated_at=NOW,
            ),
        ),
        selected_at=NOW,
        selection_delta_target=0.60,
    )


def test_default_one_lot_uses_buffered_limit_price() -> None:
    result = (
        EntryOrderSizingPolicy()
        .calculate(
            selected_option=(
                make_selected_option(
                    lot_size=65,
                    ltp=100.0,
                )
            )
        )
    )

    assert result.preferred_lots == 1
    assert result.lot_size == 65
    assert result.requested_quantity == 65

    assert result.pricing.limit_price == 101.0

    assert (
        result.required_cash
        == Decimal("6565.0")
    )


def test_two_lots_use_dynamic_contract_lot_size() -> None:
    result = (
        EntryOrderSizingPolicy()
        .calculate(
            selected_option=(
                make_selected_option(
                    lot_size=75,
                    ltp=100.02,
                )
            ),
            preferred_lots=2,
        )
    )

    assert result.preferred_lots == 2
    assert result.lot_size == 75
    assert result.requested_quantity == 150

    # 100.02 + 1.00 = 101.02
    # rounded upward to 0.05 tick = 101.05
    assert result.pricing.limit_price == 101.05

    assert (
        result.required_cash
        == Decimal("15157.50")
    )


def test_required_cash_uses_limit_not_raw_ltp() -> None:
    result = (
        EntryOrderSizingPolicy()
        .calculate(
            selected_option=(
                make_selected_option(
                    lot_size=50,
                    ltp=200.01,
                )
            ),
            preferred_lots=3,
        )
    )

    assert result.requested_quantity == 150

    assert result.pricing.reference_ltp == 200.01
    assert result.pricing.limit_price == 201.05

    assert (
        result.required_cash
        == Decimal("30157.50")
    )

    assert (
        result.required_cash
        != Decimal("30001.50")
    )


def test_custom_two_point_buffer_flows_into_cash() -> None:
    policy = EntryOrderSizingPolicy(
        pricing_policy=(
            OrderPricingPolicy(
                OrderPricingConfig(
                    entry_buffer_points=2.0
                )
            )
        )
    )

    result = policy.calculate(
        selected_option=(
            make_selected_option(
                lot_size=50,
                ltp=100.01,
            )
        ),
        preferred_lots=3,
    )

    assert result.requested_quantity == 150
    assert result.pricing.limit_price == 102.05

    assert (
        result.required_cash
        == Decimal("15307.50")
    )


@pytest.mark.parametrize(
    (
        "lot_size",
        "preferred_lots",
        "expected_quantity",
    ),
    [
        (50, 2, 100),
        (65, 4, 260),
        (75, 3, 225),
        (130, 2, 260),
    ],
)
def test_no_nifty_lot_size_is_hardcoded(
    lot_size: int,
    preferred_lots: int,
    expected_quantity: int,
) -> None:
    result = (
        EntryOrderSizingPolicy()
        .calculate(
            selected_option=(
                make_selected_option(
                    lot_size=lot_size,
                    ltp=100.0,
                )
            ),
            preferred_lots=(
                preferred_lots
            ),
        )
    )

    assert result.lot_size == lot_size

    assert (
        result.requested_quantity
        == expected_quantity
    )

    assert (
        result.required_cash
        == (
            Decimal("101.0")
            * Decimal(
                expected_quantity
            )
        )
    )


@pytest.mark.parametrize(
    "preferred_lots",
    [
        0,
        -1,
        True,
        1.5,
    ],
)
def test_invalid_preferred_lots_fail_before_sizing(
    preferred_lots,
) -> None:
    with pytest.raises(ValueError):
        (
            EntryOrderSizingPolicy()
            .calculate(
                selected_option=(
                    make_selected_option(
                        lot_size=65,
                        ltp=100.0,
                    )
                ),
                preferred_lots=(
                    preferred_lots
                ),
            )
        )
