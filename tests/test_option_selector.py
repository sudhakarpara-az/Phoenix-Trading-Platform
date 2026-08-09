from datetime import date, datetime

from src.option_selection.contract_ranker import (
    ContractRankingPolicy,
)
from src.option_selection.delta_filter import (
    DeltaEligibilityFilter,
)
from src.option_selection.expiry_selector import (
    ExpirySelectionPolicy,
)
from src.option_selection.option_chain_provider import (
    OptionChainSnapshot,
)
from src.option_selection.option_selector import (
    OptionSelectionRequest,
    OptionSelector,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionSelectionStatus,
    OptionType,
)


TRADING_DATE = date(2026, 8, 7)

EXPIRY = date(2026, 8, 13)

LATER_EXPIRY = date(2026, 8, 20)


def make_candidate(
    *,
    security_id: str,
    option_type: OptionType,
    strike: float,
    expiry: date = EXPIRY,
    delta: float,
    ltp: float = 125.0,
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
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=ltp,
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


def make_selector() -> OptionSelector:
    return OptionSelector(
        expiry_policy=ExpirySelectionPolicy(),
        delta_filter=DeltaEligibilityFilter(),
        contract_ranker=ContractRankingPolicy(),
    )


def make_snapshot(
    candidates: tuple[
        OptionCandidate,
        ...
    ],
) -> OptionChainSnapshot:
    return OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500.0,
        candidates=candidates,
        received_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
        provider_name="TEST",
    )


def make_request(
    option_type: OptionType,
    requested_expiry: date | None = None,
) -> OptionSelectionRequest:
    return OptionSelectionRequest(
        option_type=option_type,
        trading_date=TRADING_DATE,
        reference_price=24500.0,
        selected_at=datetime(
            2026,
            8,
            7,
            10,
            0,
            1,
        ),
        requested_expiry=requested_expiry,
    )


def test_empty_chain_returns_no_contracts() -> None:
    selector = make_selector()

    result = selector.select(
        make_snapshot(()),
        make_request(
            OptionType.CALL
        ),
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_CONTRACTS
    )

    assert result.selected_option is None


def test_call_request_selects_only_call() -> None:
    selector = make_selector()

    call = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    put = make_candidate(
        security_id="201",
        option_type=OptionType.PUT,
        strike=24500,
        delta=-0.64,
    )

    result = selector.select(
        make_snapshot(
            (
                put,
                call,
            )
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert (
        result.status
        is OptionSelectionStatus.SELECTED
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.option_type
        is OptionType.CALL
    )

    assert (
        result.selected_option.security_id
        == "101"
    )


def test_put_request_selects_only_put() -> None:
    selector = make_selector()

    call = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    put = make_candidate(
        security_id="201",
        option_type=OptionType.PUT,
        strike=24500,
        delta=-0.64,
    )

    result = selector.select(
        make_snapshot(
            (
                call,
                put,
            )
        ),
        make_request(
            OptionType.PUT
        ),
    )

    assert (
        result.status
        is OptionSelectionStatus.SELECTED
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.option_type
        is OptionType.PUT
    )

    assert (
        result.selected_option.security_id
        == "201"
    )


def test_nearest_expiry_is_selected() -> None:
    selector = make_selector()

    later = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        expiry=LATER_EXPIRY,
        delta=0.64,
    )

    nearest = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24600,
        expiry=EXPIRY,
        delta=0.64,
    )

    result = selector.select(
        make_snapshot(
            (
                later,
                nearest,
            )
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.expiry
        == EXPIRY
    )

    assert (
        result.selected_option.security_id
        == "102"
    )


def test_requested_expiry_is_respected() -> None:
    selector = make_selector()

    nearest = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        expiry=EXPIRY,
        delta=0.64,
    )

    requested = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24600,
        expiry=LATER_EXPIRY,
        delta=0.64,
    )

    result = selector.select(
        make_snapshot(
            (
                nearest,
                requested,
            )
        ),
        make_request(
            OptionType.CALL,
            requested_expiry=LATER_EXPIRY,
        ),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.expiry
        == LATER_EXPIRY
    )


def test_missing_requested_expiry_returns_no_valid_expiry() -> None:
    selector = make_selector()

    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        expiry=EXPIRY,
        delta=0.64,
    )

    result = selector.select(
        make_snapshot(
            (candidate,)
        ),
        make_request(
            OptionType.CALL,
            requested_expiry=LATER_EXPIRY,
        ),
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_VALID_EXPIRY
    )


def test_out_of_range_delta_is_rejected() -> None:
    selector = make_selector()

    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.75,
    )

    result = selector.select(
        make_snapshot(
            (candidate,)
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_DELTA_MATCH
    )


def test_candidate_closest_to_060_is_selected() -> None:
    selector = make_selector()

    delta_60 = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24400,
        delta=0.60,
    )

    delta_63 = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.63,
    )

    delta_64 = make_candidate(
        security_id="103",
        option_type=OptionType.CALL,
        strike=24600,
        delta=0.64,
    )

    delta_68 = make_candidate(
        security_id="104",
        option_type=OptionType.CALL,
        strike=24700,
        delta=0.68,
    )

    result = selector.select(
        make_snapshot(
            (
                delta_60,
                delta_68,
                delta_63,
                delta_64,
            )
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.security_id
        == "101"
    )

    assert (
        result.selected_option.delta
        == 0.60
    )


def test_put_delta_ranking_uses_absolute_value() -> None:
    selector = make_selector()

    delta_60 = make_candidate(
        security_id="201",
        option_type=OptionType.PUT,
        strike=24600,
        delta=-0.60,
    )

    delta_64 = make_candidate(
        security_id="202",
        option_type=OptionType.PUT,
        strike=24500,
        delta=-0.64,
    )

    result = selector.select(
        make_snapshot(
            (
                delta_60,
                delta_64,
            )
        ),
        make_request(
            OptionType.PUT
        ),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.security_id
        == "201"
    )

    assert (
        result.selected_option.delta
        == -0.60
    )

    assert (
        result.selected_option.delta_magnitude
        == 0.60
    )


def test_tighter_spread_breaks_equal_delta_tie() -> None:
    selector = make_selector()

    wide = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        bid=120,
        ask=130,
    )

    tight = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24600,
        delta=0.64,
        bid=124,
        ask=126,
    )

    result = selector.select(
        make_snapshot(
            (
                wide,
                tight,
            )
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.security_id
        == "102"
    )


def test_selected_option_preserves_lot_size() -> None:
    selector = make_selector()

    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    result = selector.select(
        make_snapshot(
            (candidate,)
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.lot_size
        == 65
    )


def test_selected_option_preserves_ltp() -> None:
    selector = make_selector()

    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        ltp=132.50,
    )

    result = selector.select(
        make_snapshot(
            (candidate,)
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.ltp
        == 132.50
    )


def test_selected_delta_target_is_060() -> None:
    selector = make_selector()

    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.63,
    )

    result = selector.select(
        make_snapshot(
            (candidate,)
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.selection_delta_target
        == 0.60
    )


def test_expired_candidate_returns_no_valid_expiry() -> None:
    selector = make_selector()

    expired = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        expiry=date(
            2026,
            8,
            6,
        ),
        delta=0.64,
    )

    result = selector.select(
        make_snapshot(
            (expired,)
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_VALID_EXPIRY
    )


def test_wrong_side_only_returns_no_contracts() -> None:
    selector = make_selector()

    put = make_candidate(
        security_id="201",
        option_type=OptionType.PUT,
        strike=24500,
        delta=-0.64,
    )

    result = selector.select(
        make_snapshot(
            (put,)
        ),
        make_request(
            OptionType.CALL
        ),
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_CONTRACTS
    )