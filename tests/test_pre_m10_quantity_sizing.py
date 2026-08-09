from datetime import (
    date,
    datetime,
)

import pytest

from src.execution.quantity_policy import (
    QuantityPolicy,
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
                ltp=205.0,
                bid=204.40,
                ask=204.90,
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


def test_default_preference_is_one_lot() -> None:
    result = (
        QuantityPolicy()
        .calculate_from_lots(
            make_selected_option(
                lot_size=65
            )
        )
    )

    assert result.preferred_lots == 1
    assert result.lot_size == 65
    assert result.requested_quantity == 65


def test_two_preferred_lots_use_contract_lot_size() -> None:
    result = (
        QuantityPolicy()
        .calculate_from_lots(
            make_selected_option(
                lot_size=65
            ),
            preferred_lots=2,
        )
    )

    assert result.preferred_lots == 2
    assert result.lot_size == 65
    assert result.requested_quantity == 130


@pytest.mark.parametrize(
    (
        "lot_size",
        "preferred_lots",
        "expected_quantity",
    ),
    [
        (50, 1, 50),
        (50, 3, 150),
        (65, 4, 260),
        (75, 2, 150),
        (130, 2, 260),
    ],
)
def test_quantity_uses_dynamic_contract_lot_size(
    lot_size: int,
    preferred_lots: int,
    expected_quantity: int,
) -> None:
    result = (
        QuantityPolicy()
        .calculate_from_lots(
            make_selected_option(
                lot_size=lot_size
            ),
            preferred_lots=(
                preferred_lots
            ),
        )
    )

    assert result.lot_size == lot_size

    assert (
        result.preferred_lots
        == preferred_lots
    )

    assert (
        result.requested_quantity
        == expected_quantity
    )


@pytest.mark.parametrize(
    "preferred_lots",
    [
        0,
        -1,
        -10,
    ],
)
def test_non_positive_preferred_lots_fail_closed(
    preferred_lots: int,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            "preferred_lots must be "
            "greater than zero"
        ),
    ):
        (
            QuantityPolicy()
            .calculate_from_lots(
                make_selected_option(
                    lot_size=65
                ),
                preferred_lots=(
                    preferred_lots
                ),
            )
        )


@pytest.mark.parametrize(
    "preferred_lots",
    [
        True,
        False,
        1.5,
        "2",
    ],
)
def test_non_integer_preferred_lots_fail_closed(
    preferred_lots,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            "preferred_lots must be "
            "an integer"
        ),
    ):
        (
            QuantityPolicy()
            .calculate_from_lots(
                make_selected_option(
                    lot_size=65
                ),
                preferred_lots=(
                    preferred_lots
                ),
            )
        )


def test_calculated_quantity_passes_existing_validation() -> None:
    policy = QuantityPolicy()

    selected_option = (
        make_selected_option(
            lot_size=75
        )
    )

    calculation = (
        policy.calculate_from_lots(
            selected_option,
            preferred_lots=3,
        )
    )

    validation = policy.validate(
        selected_option=selected_option,
        quantity=(
            calculation.requested_quantity
        ),
    )

    assert validation.valid is True
    assert validation.lot_size == 75
    assert validation.lot_count == 3
    assert validation.requested_quantity == 225
