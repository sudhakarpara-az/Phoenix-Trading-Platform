from datetime import date, datetime

from src.option_selection.expiry_selector import (
    ExpirySelectionPolicy,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
)


TRADING_DATE = date(2026, 8, 7)


def make_candidate(
    *,
    security_id: str,
    expiry: date,
    strike: float = 24500.0,
    option_type: OptionType = OptionType.CALL,
    delta: float = 0.64,
) -> OptionCandidate:
    contract = OptionContract(
        underlying_symbol="NIFTY 50",
        symbol=f"NIFTY-{security_id}",
        security_id=security_id,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        lot_size=65,
    )

    quote = OptionQuote(
        ltp=125.0,
        received_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )

    greeks = OptionGreeks(
        delta=delta,
        calculated_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )

    return OptionCandidate(
        contract=contract,
        quote=quote,
        greeks=greeks,
    )


def test_empty_candidates_returns_no_expiry() -> None:
    policy = ExpirySelectionPolicy()

    result = policy.select(
        candidates=(),
        trading_date=TRADING_DATE,
    )

    assert result.selected is False
    assert result.expiry is None
    assert result.candidates == ()
    assert result.count == 0


def test_selects_nearest_valid_expiry() -> None:
    nearest = date(2026, 8, 13)
    later = date(2026, 8, 20)

    first = make_candidate(
        security_id="101",
        expiry=later,
    )

    second = make_candidate(
        security_id="102",
        expiry=nearest,
    )

    result = ExpirySelectionPolicy().select(
        candidates=(
            first,
            second,
        ),
        trading_date=TRADING_DATE,
    )

    assert result.selected is True
    assert result.expiry == nearest
    assert result.candidates == (second,)


def test_all_candidates_for_selected_expiry_are_returned() -> None:
    expiry = date(2026, 8, 13)

    first = make_candidate(
        security_id="101",
        expiry=expiry,
        strike=24500,
    )

    second = make_candidate(
        security_id="102",
        expiry=expiry,
        strike=24600,
    )

    later = make_candidate(
        security_id="103",
        expiry=date(2026, 8, 20),
    )

    result = ExpirySelectionPolicy().select(
        candidates=(
            first,
            later,
            second,
        ),
        trading_date=TRADING_DATE,
    )

    assert result.expiry == expiry

    assert result.candidates == (
        first,
        second,
    )


def test_expired_contract_is_ignored() -> None:
    expired = make_candidate(
        security_id="101",
        expiry=date(2026, 8, 6),
    )

    valid = make_candidate(
        security_id="102",
        expiry=date(2026, 8, 13),
    )

    result = ExpirySelectionPolicy().select(
        candidates=(
            expired,
            valid,
        ),
        trading_date=TRADING_DATE,
    )

    assert result.expiry == date(2026, 8, 13)
    assert result.candidates == (valid,)


def test_all_expired_contracts_return_no_selection() -> None:
    first = make_candidate(
        security_id="101",
        expiry=date(2026, 8, 6),
    )

    second = make_candidate(
        security_id="102",
        expiry=date(2026, 7, 30),
    )

    result = ExpirySelectionPolicy().select(
        candidates=(
            first,
            second,
        ),
        trading_date=TRADING_DATE,
    )

    assert result.selected is False
    assert result.expiry is None
    assert result.candidates == ()


def test_expiry_on_trading_date_is_valid() -> None:
    same_day = make_candidate(
        security_id="101",
        expiry=TRADING_DATE,
    )

    later = make_candidate(
        security_id="102",
        expiry=date(2026, 8, 13),
    )

    result = ExpirySelectionPolicy().select(
        candidates=(
            later,
            same_day,
        ),
        trading_date=TRADING_DATE,
    )

    assert result.expiry == TRADING_DATE
    assert result.candidates == (same_day,)


def test_explicit_requested_expiry_is_selected() -> None:
    first_expiry = date(2026, 8, 13)
    requested = date(2026, 8, 20)

    first = make_candidate(
        security_id="101",
        expiry=first_expiry,
    )

    second = make_candidate(
        security_id="102",
        expiry=requested,
    )

    result = ExpirySelectionPolicy().select(
        candidates=(
            first,
            second,
        ),
        trading_date=TRADING_DATE,
        requested_expiry=requested,
    )

    assert result.selected is True
    assert result.expiry == requested
    assert result.candidates == (second,)


def test_missing_requested_expiry_returns_no_selection() -> None:
    candidate = make_candidate(
        security_id="101",
        expiry=date(2026, 8, 13),
    )

    result = ExpirySelectionPolicy().select(
        candidates=(candidate,),
        trading_date=TRADING_DATE,
        requested_expiry=date(
            2026,
            8,
            20,
        ),
    )

    assert result.selected is False
    assert result.expiry is None
    assert result.candidates == ()


def test_expired_requested_expiry_returns_no_selection() -> None:
    expired = make_candidate(
        security_id="101",
        expiry=date(2026, 8, 6),
    )

    result = ExpirySelectionPolicy().select(
        candidates=(expired,),
        trading_date=TRADING_DATE,
        requested_expiry=date(
            2026,
            8,
            6,
        ),
    )

    assert result.selected is False
    assert result.expiry is None


def test_call_and_put_candidates_can_share_expiry() -> None:
    expiry = date(2026, 8, 13)

    call = make_candidate(
        security_id="101",
        expiry=expiry,
        option_type=OptionType.CALL,
        delta=0.64,
    )

    put = make_candidate(
        security_id="102",
        expiry=expiry,
        option_type=OptionType.PUT,
        delta=-0.64,
    )

    result = ExpirySelectionPolicy().select(
        candidates=(
            call,
            put,
        ),
        trading_date=TRADING_DATE,
    )

    assert result.expiry == expiry
    assert result.candidates == (
        call,
        put,
    )