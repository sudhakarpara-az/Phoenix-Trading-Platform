"""
M04 -> M05 integration tests.

Validates the complete broker-independent signal-to-option
selection pipeline:

TradingSignal
    -> OptionSelectionService
    -> OptionChainProvider
    -> OptionSelector
    -> ExpirySelectionPolicy
    -> DeltaEligibilityFilter
    -> ContractRankingPolicy
    -> SelectedOption

Also validates option-chain cache / freshness behavior.

No live Dhan API call or broker order occurs here.
"""

from datetime import date, datetime, timedelta

from src.option_selection.contract_ranker import (
    ContractRankingPolicy,
)
from src.option_selection.delta_filter import (
    DeltaEligibilityFilter,
)
from src.option_selection.expiry_selector import (
    ExpirySelectionPolicy,
)
from src.option_selection.option_chain_cache import (
    OptionChainCache,
    OptionChainCacheKey,
    OptionChainFreshnessConfig,
    OptionChainFreshnessGuard,
)
from src.option_selection.option_chain_provider import (
    OptionChainProvider,
    OptionChainRequest,
    OptionChainSnapshot,
)
from src.option_selection.option_selector import (
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
from src.option_selection.selection_service import (
    OptionSelectionService,
)
from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


TRADING_DATE = date(2026, 8, 7)

EXPIRY = date(2026, 8, 13)

LATER_EXPIRY = date(2026, 8, 20)

NOW = datetime(
    2026,
    8,
    7,
    10,
    0,
    5,
)


def make_signal(
    *,
    direction: SignalDirection,
    underlying_price: float = 24500.0,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-20260807-K5-000001"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=direction,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=underlying_price,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )


def make_candidate(
    *,
    security_id: str,
    option_type: OptionType,
    strike: float,
    delta: float,
    expiry: date = EXPIRY,
    ltp: float = 125.0,
    bid: float | None = 124.0,
    ask: float | None = 126.0,
    volume: int | None = 1000,
    open_interest: int | None = 50000,
    received_at: datetime = NOW,
    greeks_at: datetime | None = NOW,
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
            received_at=received_at,
        ),
        greeks=OptionGreeks(
            delta=delta,
            gamma=0.001,
            theta=-4.0,
            vega=6.0,
            implied_volatility=12.0,
            calculated_at=greeks_at,
        ),
    )


class FakeProvider(
    OptionChainProvider
):
    def __init__(
        self,
        candidates: tuple[
            OptionCandidate,
            ...
        ],
    ) -> None:
        self._candidates = candidates

        self.call_count = 0

        self.last_request: (
            OptionChainRequest | None
        ) = None

    @property
    def provider_name(self) -> str:
        return "FAKE"

    def get_option_chain(
        self,
        request: OptionChainRequest,
    ) -> OptionChainSnapshot:
        self.call_count += 1
        self.last_request = request

        return OptionChainSnapshot(
            underlying_symbol=(
                request.underlying_symbol
            ),
            reference_price=(
                request.reference_price
            ),
            candidates=self._candidates,
            received_at=request.requested_at,
            provider_name=self.provider_name,
        )


def make_selector() -> OptionSelector:
    return OptionSelector(
        expiry_policy=ExpirySelectionPolicy(),
        delta_filter=DeltaEligibilityFilter(),
        contract_ranker=ContractRankingPolicy(),
    )


def make_service(
    provider: OptionChainProvider,
) -> OptionSelectionService:
    return OptionSelectionService(
        provider=provider,
        selector=make_selector(),
        supported_underlying="NIFTY 50",
    )


def make_freshness_guard():
    return OptionChainFreshnessGuard(
        OptionChainFreshnessConfig(
            snapshot_max_age_seconds=3,
            quote_max_age_seconds=3,
            greeks_max_age_seconds=3,
        )
    )


def test_call_signal_selects_call_contract() -> None:
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

    provider = FakeProvider(
        candidates=(
            put,
            call,
        )
    )

    service = make_service(
        provider
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=NOW,
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


def test_put_signal_selects_put_contract() -> None:
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

    provider = FakeProvider(
        candidates=(
            call,
            put,
        )
    )

    result = make_service(
        provider
    ).select_for_signal(
        signal=make_signal(
            direction=SignalDirection.PUT
        ),
        requested_at=NOW,
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
        result.selected_option.delta
        == -0.64
    )


def test_delta_outside_range_is_removed() -> None:
    delta_58 = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24400,
        delta=0.58,
    )

    delta_64 = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    delta_70 = make_candidate(
        security_id="103",
        option_type=OptionType.CALL,
        strike=24600,
        delta=0.70,
    )

    result = make_service(
        FakeProvider(
            candidates=(
                delta_58,
                delta_70,
                delta_64,
            )
        )
    ).select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=NOW,
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.security_id
        == "102"
    )

    assert (
        result.selected_option.delta_magnitude
        == 0.64
    )


def test_closest_delta_to_064_wins() -> None:
    delta_59 = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24300,
        delta=0.59,
    )

    delta_62 = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24400,
        delta=0.62,
    )

    delta_64 = make_candidate(
        security_id="103",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    delta_67 = make_candidate(
        security_id="104",
        option_type=OptionType.CALL,
        strike=24600,
        delta=0.67,
    )

    delta_69 = make_candidate(
        security_id="105",
        option_type=OptionType.CALL,
        strike=24700,
        delta=0.69,
    )

    result = make_service(
        FakeProvider(
            candidates=(
                delta_69,
                delta_59,
                delta_67,
                delta_62,
                delta_64,
            )
        )
    ).select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=NOW,
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.security_id
        == "103"
    )


def test_nearest_expiry_is_used() -> None:
    nearest = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        expiry=EXPIRY,
    )

    later = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        expiry=LATER_EXPIRY,
    )

    result = make_service(
        FakeProvider(
            candidates=(
                later,
                nearest,
            )
        )
    ).select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=NOW,
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.expiry
        == EXPIRY
    )

    assert (
        result.selected_option.security_id
        == "101"
    )


def test_explicit_expiry_is_used() -> None:
    nearest = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        expiry=EXPIRY,
    )

    later = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        expiry=LATER_EXPIRY,
    )

    result = make_service(
        FakeProvider(
            candidates=(
                nearest,
                later,
            )
        )
    ).select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=NOW,
        requested_expiry=LATER_EXPIRY,
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.expiry
        == LATER_EXPIRY
    )

    assert (
        result.selected_option.security_id
        == "102"
    )


def test_no_delta_match_returns_failure() -> None:
    first = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.50,
    )

    second = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24600,
        delta=0.75,
    )

    result = make_service(
        FakeProvider(
            candidates=(
                first,
                second,
            )
        )
    ).select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_DELTA_MATCH
    )

    assert result.selected_option is None


def test_signal_underlying_price_becomes_reference_price() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    provider = FakeProvider(
        candidates=(candidate,)
    )

    service = make_service(
        provider
    )

    service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL,
            underlying_price=24618.75,
        ),
        requested_at=NOW,
    )

    assert provider.last_request is not None

    assert (
        provider.last_request.reference_price
        == 24618.75
    )


def test_selected_option_preserves_execution_inputs() -> None:
    candidate = make_candidate(
        security_id="777",
        option_type=OptionType.CALL,
        strike=24600,
        delta=0.64,
        ltp=132.75,
    )

    result = make_service(
        FakeProvider(
            candidates=(candidate,)
        )
    ).select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=NOW,
    )

    assert result.selected_option is not None

    option = result.selected_option

    assert option.security_id == "777"
    assert option.strike == 24600
    assert option.ltp == 132.75
    assert option.lot_size == 65
    assert option.selection_delta_target == 0.64


def test_fresh_snapshot_can_be_reused_from_cache() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        received_at=(
            NOW
            - timedelta(seconds=1)
        ),
        greeks_at=(
            NOW
            - timedelta(seconds=1)
        ),
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=(
            NOW
            - timedelta(seconds=1)
        ),
        provider_name="FAKE",
    )

    key = OptionChainCacheKey(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.CALL,
        expiry=EXPIRY,
    )

    cache = OptionChainCache(
        freshness_guard=(
            make_freshness_guard()
        )
    )

    cache.put(
        key,
        snapshot,
    )

    cached = cache.get_fresh(
        key,
        NOW,
    )

    assert cached is snapshot


def test_stale_snapshot_is_not_reused() -> None:
    stale_time = (
        NOW
        - timedelta(seconds=10)
    )

    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        received_at=stale_time,
        greeks_at=stale_time,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=stale_time,
        provider_name="FAKE",
    )

    key = OptionChainCacheKey(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.CALL,
        expiry=EXPIRY,
    )

    cache = OptionChainCache(
        freshness_guard=(
            make_freshness_guard()
        )
    )

    cache.put(
        key,
        snapshot,
    )

    assert (
        cache.get_fresh(
            key,
            NOW,
        )
        is None
    )


def test_stale_candidate_can_be_filtered_out() -> None:
    fresh = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
        received_at=(
            NOW
            - timedelta(seconds=1)
        ),
        greeks_at=(
            NOW
            - timedelta(seconds=1)
        ),
    )

    stale = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24600,
        delta=0.63,
        received_at=(
            NOW
            - timedelta(seconds=10)
        ),
        greeks_at=(
            NOW
            - timedelta(seconds=10)
        ),
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(
            stale,
            fresh,
        ),
        received_at=(
            NOW
            - timedelta(seconds=1)
        ),
        provider_name="FAKE",
    )

    guard = make_freshness_guard()

    candidates = (
        guard.filter_fresh_candidates(
            snapshot,
            NOW,
        )
    )

    assert candidates == (
        fresh,
    )


def test_put_absolute_delta_rule_survives_full_pipeline() -> None:
    put_60 = make_candidate(
        security_id="201",
        option_type=OptionType.PUT,
        strike=24600,
        delta=-0.60,
    )

    put_64 = make_candidate(
        security_id="202",
        option_type=OptionType.PUT,
        strike=24500,
        delta=-0.64,
    )

    put_70 = make_candidate(
        security_id="203",
        option_type=OptionType.PUT,
        strike=24400,
        delta=-0.70,
    )

    result = make_service(
        FakeProvider(
            candidates=(
                put_60,
                put_70,
                put_64,
            )
        )
    ).select_for_signal(
        signal=make_signal(
            direction=SignalDirection.PUT
        ),
        requested_at=NOW,
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.security_id
        == "202"
    )

    assert (
        result.selected_option.delta
        == -0.64
    )

    assert (
        result.selected_option.delta_magnitude
        == 0.64
    )