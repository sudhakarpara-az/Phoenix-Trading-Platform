from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest

from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionSelectionResult,
    OptionSelectionStatus,
    OptionType,
    SelectedOption,
)


EXPIRY = date(2026, 8, 13)


def make_contract(
    option_type: OptionType = OptionType.CALL,
) -> OptionContract:
    return OptionContract(
        underlying_symbol="NIFTY 50",
        symbol="NIFTY-TEST-24500-CE",
        security_id="123456",
        option_type=option_type,
        strike=24500.0,
        expiry=EXPIRY,
        lot_size=65,
    )


def make_quote() -> OptionQuote:
    return OptionQuote(
        ltp=125.50,
        bid=125.40,
        ask=125.60,
        volume=1000,
        open_interest=50000,
        received_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )


def make_greeks(
    delta: float = 0.64,
) -> OptionGreeks:
    return OptionGreeks(
        delta=delta,
        gamma=0.001,
        theta=-4.5,
        vega=6.2,
        implied_volatility=12.5,
        calculated_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )


def make_candidate(
    option_type: OptionType = OptionType.CALL,
    delta: float = 0.64,
) -> OptionCandidate:
    return OptionCandidate(
        contract=make_contract(
            option_type=option_type,
        ),
        quote=make_quote(),
        greeks=make_greeks(
            delta=delta,
        ),
    )


def test_call_option_type_exists() -> None:
    assert OptionType.CALL.value == "CALL"


def test_put_option_type_exists() -> None:
    assert OptionType.PUT.value == "PUT"


def test_option_contract_creation() -> None:
    contract = make_contract()

    assert contract.underlying_symbol == "NIFTY 50"
    assert contract.strike == 24500.0
    assert contract.expiry == EXPIRY
    assert contract.lot_size == 65


def test_option_contract_is_immutable() -> None:
    contract = make_contract()

    with pytest.raises(FrozenInstanceError):
        contract.strike = 25000.0  # type: ignore[misc]


def test_empty_contract_symbol_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="symbol cannot be empty",
    ):
        OptionContract(
            underlying_symbol="NIFTY 50",
            symbol=" ",
            security_id="123456",
            option_type=OptionType.CALL,
            strike=24500.0,
            expiry=EXPIRY,
            lot_size=65,
        )


def test_empty_security_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="security_id cannot be empty",
    ):
        OptionContract(
            underlying_symbol="NIFTY 50",
            symbol="NIFTY TEST",
            security_id=" ",
            option_type=OptionType.CALL,
            strike=24500.0,
            expiry=EXPIRY,
            lot_size=65,
        )


def test_invalid_strike_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="strike must be greater than zero",
    ):
        OptionContract(
            underlying_symbol="NIFTY 50",
            symbol="NIFTY TEST",
            security_id="123",
            option_type=OptionType.CALL,
            strike=0,
            expiry=EXPIRY,
            lot_size=65,
        )


def test_invalid_lot_size_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="lot_size must be greater than zero",
    ):
        OptionContract(
            underlying_symbol="NIFTY 50",
            symbol="NIFTY TEST",
            security_id="123",
            option_type=OptionType.CALL,
            strike=24500,
            expiry=EXPIRY,
            lot_size=0,
        )


def test_option_quote_creation() -> None:
    quote = make_quote()

    assert quote.ltp == 125.50
    assert quote.bid == 125.40
    assert quote.ask == 125.60
    assert quote.volume == 1000


def test_zero_ltp_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="ltp must be greater than zero",
    ):
        OptionQuote(
            ltp=0,
            received_at=datetime.now(),
        )


def test_bid_above_ask_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="bid cannot be greater than ask",
    ):
        OptionQuote(
            ltp=125,
            bid=126,
            ask=125,
            received_at=datetime.now(),
        )


def test_negative_volume_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="volume cannot be negative",
    ):
        OptionQuote(
            ltp=125,
            volume=-1,
            received_at=datetime.now(),
        )


def test_call_delta_magnitude() -> None:
    greeks = make_greeks(
        delta=0.64
    )

    assert greeks.delta == 0.64
    assert greeks.delta_magnitude == 0.64


def test_put_delta_magnitude() -> None:
    greeks = make_greeks(
        delta=-0.64
    )

    assert greeks.delta == -0.64
    assert greeks.delta_magnitude == 0.64


def test_delta_above_one_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="delta must be between -1 and 1",
    ):
        make_greeks(
            delta=1.1
        )


def test_delta_below_negative_one_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="delta must be between -1 and 1",
    ):
        make_greeks(
            delta=-1.1
        )


def test_candidate_exposes_quote_and_delta() -> None:
    candidate = make_candidate()

    assert candidate.ltp == 125.50
    assert candidate.delta == 0.64
    assert candidate.delta_magnitude == 0.64


def test_put_candidate_preserves_negative_delta() -> None:
    candidate = make_candidate(
        option_type=OptionType.PUT,
        delta=-0.63,
    )

    assert candidate.delta == -0.63
    assert candidate.delta_magnitude == 0.63
    assert candidate.contract.option_type is OptionType.PUT


def test_selected_option_exposes_contract_data() -> None:
    selected = SelectedOption(
        candidate=make_candidate(),
        selected_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
        selection_delta_target=0.64,
    )

    assert selected.security_id == "123456"
    assert selected.strike == 24500
    assert selected.option_type is OptionType.CALL
    assert selected.delta == 0.64
    assert selected.ltp == 125.50
    assert selected.lot_size == 65


def test_invalid_selection_delta_target_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="selection_delta_target must be between 0 and 1",
    ):
        SelectedOption(
            candidate=make_candidate(),
            selected_at=datetime.now(),
            selection_delta_target=0,
        )


def test_success_result_requires_selected_option() -> None:
    with pytest.raises(
        ValueError,
        match="SELECTED result must contain selected_option",
    ):
        OptionSelectionResult(
            status=OptionSelectionStatus.SELECTED,
        )


def test_successful_selection_result() -> None:
    selected = SelectedOption(
        candidate=make_candidate(),
        selected_at=datetime.now(),
        selection_delta_target=0.64,
    )

    result = OptionSelectionResult(
        status=OptionSelectionStatus.SELECTED,
        selected_option=selected,
    )

    assert (
        result.status
        is OptionSelectionStatus.SELECTED
    )

    assert result.selected_option is selected


def test_failed_result_cannot_contain_option() -> None:
    selected = SelectedOption(
        candidate=make_candidate(),
        selected_at=datetime.now(),
        selection_delta_target=0.64,
    )

    with pytest.raises(
        ValueError,
        match="failed selection result cannot contain selected_option",
    ):
        OptionSelectionResult(
            status=OptionSelectionStatus.NO_DELTA_MATCH,
            selected_option=selected,
        )


def test_failure_result_can_include_message() -> None:
    result = OptionSelectionResult(
        status=OptionSelectionStatus.NO_DELTA_MATCH,
        message="No option matched configured delta range",
    )

    assert result.selected_option is None
    assert (
        result.status
        is OptionSelectionStatus.NO_DELTA_MATCH
    )