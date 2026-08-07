from datetime import date, datetime

import pytest

from src.option_selection.contract_ranker import (
    ContractRankingConfig,
    ContractRankingPolicy,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
)


EXPIRY = date(2026, 8, 13)


def make_candidate(
    *,
    security_id: str,
    strike: float,
    delta: float,
    bid: float | None = 124.0,
    ask: float | None = 126.0,
    volume: int | None = 1000,
    open_interest: int | None = 50000,
) -> OptionCandidate:
    return OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol=f"NIFTY-{security_id}",
            security_id=security_id,
            option_type=OptionType.CALL,
            strike=strike,
            expiry=EXPIRY,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=125.0,
            bid=bid,
            ask=ask,
            volume=volume,
            open_interest=open_interest,
            received_at=datetime(
                2026,
                8,
                7,
                10,
                0,
            ),
        ),
        greeks=OptionGreeks(
            delta=delta,
            calculated_at=datetime(
                2026,
                8,
                7,
                10,
                0,
            ),
        ),
    )


def test_default_preferred_delta() -> None:
    config = ContractRankingConfig()

    assert config.preferred_delta == 0.64


def test_exact_preferred_delta_ranks_first() -> None:
    ranker = ContractRankingPolicy()

    first = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.60,
    )

    preferred = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.64,
    )

    third = make_candidate(
        security_id="103",
        strike=24700,
        delta=0.68,
    )

    ranked = ranker.rank(
        (
            first,
            preferred,
            third,
        ),
        reference_price=24550,
    )

    assert ranked[0].candidate is preferred
    assert ranked[0].rank == 1


def test_closest_delta_ranks_first() -> None:
    ranker = ContractRankingPolicy()

    delta_60 = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.60,
    )

    delta_63 = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.63,
    )

    delta_68 = make_candidate(
        security_id="103",
        strike=24700,
        delta=0.68,
    )

    ranked = ranker.rank(
        (
            delta_60,
            delta_68,
            delta_63,
        ),
        reference_price=24550,
    )

    assert ranked[0].candidate is delta_63


def test_put_negative_delta_uses_magnitude() -> None:
    candidate = OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol="NIFTY-PUT",
            security_id="201",
            option_type=OptionType.PUT,
            strike=24500,
            expiry=EXPIRY,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=125,
            bid=124,
            ask=126,
            volume=1000,
            open_interest=50000,
            received_at=datetime.now(),
        ),
        greeks=OptionGreeks(
            delta=-0.64,
            calculated_at=datetime.now(),
        ),
    )

    ranker = ContractRankingPolicy()

    ranked = ranker.rank(
        (candidate,),
        reference_price=24500,
    )

    assert ranked[0].delta_distance == pytest.approx(0)


def test_smaller_spread_breaks_equal_delta_tie() -> None:
    ranker = ContractRankingPolicy()

    wide = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.64,
        bid=120,
        ask=130,
    )

    tight = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.64,
        bid=124,
        ask=126,
    )

    ranked = ranker.rank(
        (
            wide,
            tight,
        ),
        reference_price=24500,
    )

    assert ranked[0].candidate is tight


def test_higher_volume_breaks_equal_spread_tie() -> None:
    ranker = ContractRankingPolicy()

    low_volume = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.64,
        volume=100,
    )

    high_volume = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.64,
        volume=10000,
    )

    ranked = ranker.rank(
        (
            low_volume,
            high_volume,
        ),
        reference_price=24500,
    )

    assert ranked[0].candidate is high_volume


def test_higher_oi_breaks_equal_volume_tie() -> None:
    ranker = ContractRankingPolicy()

    low_oi = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.64,
        open_interest=10000,
    )

    high_oi = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.64,
        open_interest=90000,
    )

    ranked = ranker.rank(
        (
            low_oi,
            high_oi,
        ),
        reference_price=24500,
    )

    assert ranked[0].candidate is high_oi


def test_closer_strike_breaks_remaining_tie() -> None:
    ranker = ContractRankingPolicy()

    far = make_candidate(
        security_id="101",
        strike=24800,
        delta=0.64,
    )

    close = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.64,
    )

    ranked = ranker.rank(
        (
            far,
            close,
        ),
        reference_price=24550,
    )

    assert ranked[0].candidate is close


def test_security_id_provides_stable_final_tie_break() -> None:
    ranker = ContractRankingPolicy()

    second = make_candidate(
        security_id="200",
        strike=24500,
        delta=0.64,
    )

    first = make_candidate(
        security_id="100",
        strike=24500,
        delta=0.64,
    )

    ranked = ranker.rank(
        (
            second,
            first,
        ),
        reference_price=24500,
    )

    assert ranked[0].candidate is first


def test_missing_spread_ranks_after_available_spread() -> None:
    ranker = ContractRankingPolicy()

    missing = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.64,
        bid=None,
        ask=None,
    )

    available = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.64,
        bid=124,
        ask=126,
    )

    ranked = ranker.rank(
        (
            missing,
            available,
        ),
        reference_price=24500,
    )

    assert ranked[0].candidate is available


def test_missing_volume_ranks_after_known_volume() -> None:
    ranker = ContractRankingPolicy()

    missing = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.64,
        volume=None,
    )

    known = make_candidate(
        security_id="102",
        strike=24500,
        delta=0.64,
        volume=100,
    )

    ranked = ranker.rank(
        (
            missing,
            known,
        ),
        reference_price=24500,
    )

    assert ranked[0].candidate is known


def test_best_returns_best_candidate() -> None:
    ranker = ContractRankingPolicy()

    first = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.60,
    )

    best = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.64,
    )

    result = ranker.best(
        (
            first,
            best,
        ),
        reference_price=24500,
    )

    assert result is best


def test_best_empty_input_returns_none() -> None:
    ranker = ContractRankingPolicy()

    assert ranker.best(
        (),
        reference_price=24500,
    ) is None


def test_rank_empty_input_returns_empty() -> None:
    ranker = ContractRankingPolicy()

    assert ranker.rank(
        (),
        reference_price=24500,
    ) == ()


def test_invalid_reference_price_rejected() -> None:
    ranker = ContractRankingPolicy()

    with pytest.raises(
        ValueError,
        match="reference_price must be greater than zero",
    ):
        ranker.rank(
            (),
            reference_price=0,
        )


def test_custom_preferred_delta() -> None:
    ranker = ContractRankingPolicy(
        ContractRankingConfig(
            preferred_delta=0.65
        )
    )

    delta_64 = make_candidate(
        security_id="101",
        strike=24500,
        delta=0.64,
    )

    delta_65 = make_candidate(
        security_id="102",
        strike=24600,
        delta=0.65,
    )

    ranked = ranker.rank(
        (
            delta_64,
            delta_65,
        ),
        reference_price=24500,
    )

    assert ranked[0].candidate is delta_65


def test_invalid_preferred_delta_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="preferred_delta must be between 0 and 1",
    ):
        ContractRankingConfig(
            preferred_delta=0
        )