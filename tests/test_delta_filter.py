from datetime import date, datetime

import pytest

from src.option_selection.delta_filter import (
    DeltaEligibilityFilter,
    DeltaFilterConfig,
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
    delta: float,
    option_type: OptionType = OptionType.CALL,
) -> OptionCandidate:
    return OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol=(
                f"NIFTY-{security_id}-"
                f"{option_type.value}"
            ),
            security_id=security_id,
            option_type=option_type,
            strike=24500.0,
            expiry=EXPIRY,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=125.0,
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


def test_default_configuration() -> None:
    config = DeltaFilterConfig()

    assert config.minimum_delta == 0.59
    assert config.maximum_delta == 0.69
    assert config.preferred_delta == 0.64


def test_call_at_lower_boundary_is_eligible() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="101",
        delta=0.59,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is True


def test_call_at_upper_boundary_is_eligible() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="101",
        delta=0.69,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is True


def test_call_preferred_delta_is_eligible() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="101",
        delta=0.64,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is True


def test_call_below_range_is_rejected() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="101",
        delta=0.58,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is False


def test_call_above_range_is_rejected() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="101",
        delta=0.70,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is False


def test_put_at_lower_boundary_is_eligible() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="201",
        delta=-0.59,
        option_type=OptionType.PUT,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is True


def test_put_at_upper_boundary_is_eligible() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="201",
        delta=-0.69,
        option_type=OptionType.PUT,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is True


def test_put_preferred_delta_is_eligible() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="201",
        delta=-0.64,
        option_type=OptionType.PUT,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is True


def test_put_below_range_is_rejected() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="201",
        delta=-0.58,
        option_type=OptionType.PUT,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is False


def test_put_above_range_is_rejected() -> None:
    delta_filter = DeltaEligibilityFilter()

    candidate = make_candidate(
        security_id="201",
        delta=-0.70,
        option_type=OptionType.PUT,
    )

    assert delta_filter.is_eligible(
        candidate
    ) is False


def test_filter_returns_only_eligible_candidates() -> None:
    delta_filter = DeltaEligibilityFilter()

    below = make_candidate(
        security_id="101",
        delta=0.58,
    )

    lower = make_candidate(
        security_id="102",
        delta=0.59,
    )

    preferred = make_candidate(
        security_id="103",
        delta=0.64,
    )

    upper = make_candidate(
        security_id="104",
        delta=0.69,
    )

    above = make_candidate(
        security_id="105",
        delta=0.70,
    )

    result = delta_filter.filter(
        (
            below,
            lower,
            preferred,
            upper,
            above,
        )
    )

    assert result.eligible == (
        lower,
        preferred,
        upper,
    )

    assert result.total_candidates == 5
    assert result.rejected_candidates == 2
    assert result.count == 3
    assert result.has_matches is True


def test_filter_preserves_call_and_put_candidates() -> None:
    delta_filter = DeltaEligibilityFilter()

    call = make_candidate(
        security_id="101",
        delta=0.63,
        option_type=OptionType.CALL,
    )

    put = make_candidate(
        security_id="201",
        delta=-0.65,
        option_type=OptionType.PUT,
    )

    result = delta_filter.filter(
        (
            call,
            put,
        )
    )

    assert result.eligible == (
        call,
        put,
    )


def test_empty_input_returns_empty_result() -> None:
    delta_filter = DeltaEligibilityFilter()

    result = delta_filter.filter(())

    assert result.eligible == ()
    assert result.total_candidates == 0
    assert result.rejected_candidates == 0
    assert result.count == 0
    assert result.has_matches is False


def test_no_matching_delta_returns_empty_result() -> None:
    delta_filter = DeltaEligibilityFilter()

    first = make_candidate(
        security_id="101",
        delta=0.50,
    )

    second = make_candidate(
        security_id="102",
        delta=0.75,
    )

    result = delta_filter.filter(
        (
            first,
            second,
        )
    )

    assert result.eligible == ()
    assert result.total_candidates == 2
    assert result.rejected_candidates == 2
    assert result.has_matches is False


def test_custom_delta_range() -> None:
    delta_filter = DeltaEligibilityFilter(
        config=DeltaFilterConfig(
            minimum_delta=0.60,
            maximum_delta=0.70,
            preferred_delta=0.65,
        )
    )

    rejected = make_candidate(
        security_id="101",
        delta=0.59,
    )

    accepted = make_candidate(
        security_id="102",
        delta=0.65,
    )

    assert delta_filter.is_eligible(
        rejected
    ) is False

    assert delta_filter.is_eligible(
        accepted
    ) is True


def test_minimum_above_maximum_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "minimum_delta cannot be greater "
            "than maximum_delta"
        ),
    ):
        DeltaFilterConfig(
            minimum_delta=0.70,
            maximum_delta=0.60,
            preferred_delta=0.65,
        )


def test_preferred_delta_below_range_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "preferred_delta must be within "
            "configured delta range"
        ),
    ):
        DeltaFilterConfig(
            minimum_delta=0.59,
            maximum_delta=0.69,
            preferred_delta=0.58,
        )


def test_preferred_delta_above_range_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "preferred_delta must be within "
            "configured delta range"
        ),
    ):
        DeltaFilterConfig(
            minimum_delta=0.59,
            maximum_delta=0.69,
            preferred_delta=0.70,
        )


def test_zero_delta_configuration_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="minimum_delta must be between 0 and 1",
    ):
        DeltaFilterConfig(
            minimum_delta=0,
            maximum_delta=0.69,
            preferred_delta=0.64,
        )