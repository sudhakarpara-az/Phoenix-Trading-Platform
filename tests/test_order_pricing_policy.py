from datetime import date, datetime

import pytest

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


EXPIRY = date(2026, 8, 11)
NOW = datetime(2026, 8, 7, 14, 30)


def make_selected_option(
    *,
    ltp: float = 205.0,
) -> SelectedOption:
    candidate = OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol="NIFTY50-20260811-24450-CE",
            security_id="41009",
            option_type=OptionType.CALL,
            strike=24450.0,
            expiry=EXPIRY,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=ltp,
            bid=204.40,
            ask=204.90,
            volume=1000,
            open_interest=50000,
            received_at=NOW,
        ),
        greeks=OptionGreeks(
            delta=0.64,
            calculated_at=NOW,
        ),
    )

    return SelectedOption(
        candidate=candidate,
        selected_at=NOW,
        selection_delta_target=0.64,
    )


def test_default_configuration() -> None:
    config = OrderPricingConfig()

    assert config.entry_buffer_points == 1.0
    assert config.tick_size == 0.05


def test_default_one_point_buffer() -> None:
    policy = OrderPricingPolicy()

    price = policy.calculate(
        make_selected_option(
            ltp=205.0
        )
    )

    assert price.reference_ltp == 205.0
    assert price.buffer_points == 1.0
    assert price.raw_price == 206.0
    assert price.limit_price == 206.0


def test_two_point_buffer() -> None:
    policy = OrderPricingPolicy(
        OrderPricingConfig(
            entry_buffer_points=2.0,
            tick_size=0.05,
        )
    )

    price = policy.calculate(
        make_selected_option(
            ltp=205.0
        )
    )

    assert price.raw_price == 207.0
    assert price.limit_price == 207.0


def test_fractional_buffer_allowed() -> None:
    policy = OrderPricingPolicy(
        OrderPricingConfig(
            entry_buffer_points=1.5,
            tick_size=0.05,
        )
    )

    price = policy.calculate(
        make_selected_option(
            ltp=205.0
        )
    )

    assert price.raw_price == 206.5
    assert price.limit_price == 206.5


def test_price_already_on_tick_is_unchanged() -> None:
    policy = OrderPricingPolicy(
        OrderPricingConfig(
            entry_buffer_points=1.0,
            tick_size=0.05,
        )
    )

    price = policy.calculate(
        make_selected_option(
            ltp=204.05
        )
    )

    assert price.raw_price == 205.05
    assert price.limit_price == 205.05


def test_price_is_rounded_up_to_tick() -> None:
    policy = OrderPricingPolicy(
        OrderPricingConfig(
            entry_buffer_points=1.0,
            tick_size=0.05,
        )
    )

    price = policy.calculate(
        make_selected_option(
            ltp=204.01
        )
    )

    assert price.raw_price == pytest.approx(
        205.01
    )

    assert price.limit_price == 205.05


def test_price_never_rounds_below_raw_price() -> None:
    policy = OrderPricingPolicy()

    result = policy.calculate(
        make_selected_option(
            ltp=132.73
        )
    )

    assert (
        result.limit_price
        >= result.raw_price
    )


def test_live_like_call_example() -> None:
    policy = OrderPricingPolicy(
        OrderPricingConfig(
            entry_buffer_points=1.0
        )
    )

    result = policy.calculate(
        make_selected_option(
            ltp=205.0
        )
    )

    assert result.limit_price == 206.0


def test_live_like_put_ltp_example() -> None:
    policy = OrderPricingPolicy(
        OrderPricingConfig(
            entry_buffer_points=1.0
        )
    )

    result = policy.calculate(
        make_selected_option(
            ltp=132.75
        )
    )

    assert result.limit_price == 133.75


def test_buffer_below_one_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "entry_buffer_points must be "
            "between 1 and 2"
        ),
    ):
        OrderPricingConfig(
            entry_buffer_points=0.99
        )


def test_buffer_above_two_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "entry_buffer_points must be "
            "between 1 and 2"
        ),
    ):
        OrderPricingConfig(
            entry_buffer_points=2.01
        )


def test_zero_tick_size_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "tick_size must be greater than zero"
        ),
    ):
        OrderPricingConfig(
            tick_size=0
        )


def test_custom_tick_size() -> None:
    policy = OrderPricingPolicy(
        OrderPricingConfig(
            entry_buffer_points=1.0,
            tick_size=0.10,
        )
    )

    result = policy.calculate(
        make_selected_option(
            ltp=100.04
        )
    )

    assert result.raw_price == pytest.approx(
        101.04
    )

    assert result.limit_price == 101.10