from datetime import date, datetime

import pytest

from src.execution.quantity_policy import QuantityPolicy

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
    lot_size: int = 65,
) -> SelectedOption:
    candidate = OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol="NIFTY50-20260811-24450-CE",
            security_id="41009",
            option_type=OptionType.CALL,
            strike=24450.0,
            expiry=EXPIRY,
            lot_size=lot_size,
        ),
        quote=OptionQuote(
            ltp=205.0,
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


def test_one_lot_is_valid() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=65,
    )

    assert result.valid is True
    assert result.lot_size == 65
    assert result.lot_count == 1


def test_two_lots_are_valid() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=130,
    )

    assert result.valid is True
    assert result.lot_count == 2


def test_three_lots_are_valid() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=195,
    )

    assert result.valid is True
    assert result.lot_count == 3


def test_zero_quantity_is_rejected() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=0,
    )

    assert result.valid is False
    assert result.lot_count is None
    assert result.message == (
        "quantity must be greater than zero"
    )


def test_negative_quantity_is_rejected() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=-65,
    )

    assert result.valid is False


def test_quantity_below_one_lot_is_rejected() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=64,
    )

    assert result.valid is False

    assert result.message == (
        "quantity must be an exact multiple "
        "of option lot size"
    )


def test_non_multiple_quantity_is_rejected() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=100,
    )

    assert result.valid is False


def test_quantity_one_above_lot_is_rejected() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=66,
    )

    assert result.valid is False


def test_large_valid_quantity() -> None:
    policy = QuantityPolicy()

    result = policy.validate(
        selected_option=make_selected_option(),
        quantity=650,
    )

    assert result.valid is True
    assert result.lot_count == 10


def test_custom_contract_lot_size_is_respected() -> None:
    policy = QuantityPolicy()

    selected_option = make_selected_option(
        lot_size=50
    )

    result = policy.validate(
        selected_option=selected_option,
        quantity=150,
    )

    assert result.valid is True
    assert result.lot_size == 50
    assert result.lot_count == 3


def test_custom_lot_size_non_multiple_rejected() -> None:
    policy = QuantityPolicy()

    selected_option = make_selected_option(
        lot_size=50
    )

    result = policy.validate(
        selected_option=selected_option,
        quantity=125,
    )

    assert result.valid is False


def test_require_valid_returns_lot_count() -> None:
    policy = QuantityPolicy()

    lots = policy.require_valid(
        selected_option=make_selected_option(),
        quantity=130,
    )

    assert lots == 2


def test_require_valid_raises_for_invalid_quantity() -> None:
    policy = QuantityPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "quantity must be an exact multiple "
            "of option lot size"
        ),
    ):
        policy.require_valid(
            selected_option=make_selected_option(),
            quantity=100,
        )