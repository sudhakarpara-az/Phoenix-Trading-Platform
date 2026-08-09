"""
M05 failure and edge-case tests.

These tests deliberately stress the Phoenix option-selection
subsystem without adding new production behavior.
"""

from datetime import date, datetime, timedelta

import pytest

from src.option_selection.contract_ranker import (
    ContractRankingPolicy,
)
from src.option_selection.delta_filter import (
    DeltaEligibilityFilter,
)
from src.option_selection.dhan_option_chain_adapter import (
    DhanOptionChainAdapter,
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
from src.strategy.strategy_types import EntryLevel


TRADING_DATE = date(2026, 8, 7)
EXPIRY = date(2026, 8, 11)
NOW = datetime(2026, 8, 7, 14, 30, 0)


def make_candidate(
    *,
    security_id: str = "101",
    option_type: OptionType = OptionType.CALL,
    strike: float = 24500.0,
    expiry: date = EXPIRY,
    delta: float = 0.64,
    ltp: float = 125.0,
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
            bid=124.0,
            ask=126.0,
            volume=1000,
            open_interest=50000,
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


def make_signal(
    *,
    direction: SignalDirection = SignalDirection.CALL,
    underlying_symbol: str = "NIFTY 50",
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId("SIG-EDGE-001"),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=direction,
        instrument_security_id="12345",
        instrument_symbol="NIFTY-TEST-OPTION",
        underlying_symbol=underlying_symbol,
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )


class FakeProvider(OptionChainProvider):
    def __init__(
        self,
        candidates=(),
        *,
        fail: bool = False,
    ) -> None:
        self._candidates = candidates
        self._fail = fail

    @property
    def provider_name(self) -> str:
        return "FAKE"

    def get_option_chain(
        self,
        request: OptionChainRequest,
    ) -> OptionChainSnapshot:
        if self._fail:
            raise RuntimeError(
                "simulated provider failure"
            )

        return OptionChainSnapshot(
            underlying_symbol=request.underlying_symbol,
            reference_price=request.reference_price,
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


def make_guard() -> OptionChainFreshnessGuard:
    return OptionChainFreshnessGuard(
        OptionChainFreshnessConfig(
            snapshot_max_age_seconds=3,
            quote_max_age_seconds=3,
            greeks_max_age_seconds=3,
        )
    )


def test_provider_failure_fails_closed() -> None:
    service = make_service(
        FakeProvider(
            fail=True
        )
    )

    result = service.select_for_signal(
        signal=make_signal(),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.PROVIDER_ERROR
    )

    assert result.selected_option is None


def test_empty_chain_fails_closed() -> None:
    service = make_service(
        FakeProvider(
            candidates=()
        )
    )

    result = service.select_for_signal(
        signal=make_signal(),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_CONTRACTS
    )


def test_wrong_underlying_is_rejected() -> None:
    service = make_service(
        FakeProvider()
    )

    result = service.select_for_signal(
        signal=make_signal(
            underlying_symbol="BANKNIFTY"
        ),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.INVALID_REQUEST
    )


def test_wrong_option_side_is_not_selected() -> None:
    put_only = make_candidate(
        option_type=OptionType.PUT,
        delta=-0.64,
    )

    service = make_service(
        FakeProvider(
            candidates=(put_only,)
        )
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_CONTRACTS
    )


def test_expired_contract_is_not_selected() -> None:
    expired = make_candidate(
        expiry=date(2026, 8, 6),
    )

    service = make_service(
        FakeProvider(
            candidates=(expired,)
        )
    )

    result = service.select_for_signal(
        signal=make_signal(),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_VALID_EXPIRY
    )


def test_missing_requested_expiry_fails_closed() -> None:
    candidate = make_candidate(
        expiry=EXPIRY,
    )

    result = make_service(
        FakeProvider(
            candidates=(candidate,)
        )
    ).select_for_signal(
        signal=make_signal(),
        requested_at=NOW,
        requested_expiry=date(
            2026,
            8,
            18,
        ),
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_VALID_EXPIRY
    )


def test_delta_below_minimum_is_rejected() -> None:
    candidate = make_candidate(
        delta=0.5899,
    )

    result = make_service(
        FakeProvider(
            candidates=(candidate,)
        )
    ).select_for_signal(
        signal=make_signal(),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_DELTA_MATCH
    )


def test_delta_above_maximum_is_rejected() -> None:
    candidate = make_candidate(
        delta=0.6901,
    )

    result = make_service(
        FakeProvider(
            candidates=(candidate,)
        )
    ).select_for_signal(
        signal=make_signal(),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_DELTA_MATCH
    )


def test_delta_lower_boundary_is_allowed() -> None:
    candidate = make_candidate(
        delta=0.59,
    )

    result = make_service(
        FakeProvider(
            candidates=(candidate,)
        )
    ).select_for_signal(
        signal=make_signal(),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.SELECTED
    )


def test_delta_upper_boundary_is_allowed() -> None:
    candidate = make_candidate(
        delta=0.69,
    )

    result = make_service(
        FakeProvider(
            candidates=(candidate,)
        )
    ).select_for_signal(
        signal=make_signal(),
        requested_at=NOW,
    )

    assert (
        result.status
        is OptionSelectionStatus.SELECTED
    )


def test_put_negative_delta_boundary_is_allowed() -> None:
    candidate = make_candidate(
        option_type=OptionType.PUT,
        delta=-0.59,
    )

    result = make_service(
        FakeProvider(
            candidates=(candidate,)
        )
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


def test_stale_snapshot_is_not_fresh() -> None:
    stale_time = (
        NOW
        - timedelta(seconds=10)
    )

    candidate = make_candidate(
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

    assert make_guard().is_fresh(
        snapshot,
        NOW,
    ) is False


def test_fresh_snapshot_with_stale_quote_is_not_fresh() -> None:
    candidate = make_candidate(
        received_at=(
            NOW
            - timedelta(seconds=10)
        ),
        greeks_at=NOW,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=NOW,
        provider_name="FAKE",
    )

    result = make_guard().evaluate(
        snapshot,
        NOW,
    )

    assert result.fresh is False
    assert result.quotes_fresh is False


def test_fresh_snapshot_with_stale_greeks_is_not_fresh() -> None:
    candidate = make_candidate(
        received_at=NOW,
        greeks_at=(
            NOW
            - timedelta(seconds=10)
        ),
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=NOW,
        provider_name="FAKE",
    )

    result = make_guard().evaluate(
        snapshot,
        NOW,
    )

    assert result.fresh is False
    assert result.greeks_fresh is False


def test_missing_greeks_timestamp_is_stale() -> None:
    candidate = make_candidate(
        greeks_at=None,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=NOW,
        provider_name="FAKE",
    )

    result = make_guard().evaluate(
        snapshot,
        NOW,
    )

    assert result.fresh is False
    assert result.greeks_fresh is False


def test_future_snapshot_timestamp_is_rejected() -> None:
    future = (
        NOW
        + timedelta(seconds=1)
    )

    candidate = make_candidate(
        received_at=future,
        greeks_at=future,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=future,
        provider_name="FAKE",
    )

    assert make_guard().is_fresh(
        snapshot,
        NOW,
    ) is False


def test_stale_cache_entry_is_not_returned_as_fresh() -> None:
    stale = (
        NOW
        - timedelta(seconds=10)
    )

    candidate = make_candidate(
        received_at=stale,
        greeks_at=stale,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=stale,
        provider_name="FAKE",
    )

    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    key = OptionChainCacheKey(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.CALL,
        expiry=EXPIRY,
    )

    cache.put(
        key,
        snapshot,
    )

    assert cache.get(key) is snapshot

    assert cache.get_fresh(
        key,
        NOW,
    ) is None


def test_malformed_dhan_response_missing_oc_raises() -> None:
    class FakeDhan:
        def option_chain(
            self,
            *,
            under_security_id,
            under_exchange_segment,
            expiry,
        ):
            return {
                "status": "success",
                "remarks": "",
                "data": {
                    "status": "success",
                    "data": {
                        "last_price": 24500,
                    },
                },
            }

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhan()
    )

    request = OptionChainRequest(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.CALL,
        reference_price=24500,
        requested_at=NOW,
        expiry=EXPIRY,
    )

    with pytest.raises(
        RuntimeError,
        match="missing data.oc",
    ):
        adapter.get_option_chain(
            request
        )


def test_dhan_failure_response_raises() -> None:
    class FakeDhan:
        def option_chain(
            self,
            *,
            under_security_id,
            under_exchange_segment,
            expiry,
        ):
            return {
                "status": "failure",
                "remarks": "rate limit exceeded",
                "data": "",
            }

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhan()
    )

    request = OptionChainRequest(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.CALL,
        reference_price=24500,
        requested_at=NOW,
        expiry=EXPIRY,
    )

    with pytest.raises(
        RuntimeError,
        match="Dhan option chain failed",
    ):
        adapter.get_option_chain(
            request
        )


def test_dhan_missing_security_id_is_skipped() -> None:
    class FakeDhan:
        def option_chain(
            self,
            *,
            under_security_id,
            under_exchange_segment,
            expiry,
        ):
            return {
                "status": "success",
                "remarks": "",
                "data": {
                    "status": "success",
                    "data": {
                        "last_price": 24500,
                        "oc": {
                            "24500.000000": {
                                "ce": {
                                    "last_price": 125,
                                    "greeks": {
                                        "delta": 0.64,
                                    },
                                },
                            },
                        },
                    },
                },
            }

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhan()
    )

    snapshot = adapter.get_option_chain(
        OptionChainRequest(
            underlying_symbol="NIFTY 50",
            option_type=OptionType.CALL,
            reference_price=24500,
            requested_at=NOW,
            expiry=EXPIRY,
        )
    )

    assert snapshot.candidates == ()


def test_dhan_missing_delta_is_skipped() -> None:
    class FakeDhan:
        def option_chain(
            self,
            *,
            under_security_id,
            under_exchange_segment,
            expiry,
        ):
            return {
                "status": "success",
                "remarks": "",
                "data": {
                    "status": "success",
                    "data": {
                        "last_price": 24500,
                        "oc": {
                            "24500.000000": {
                                "ce": {
                                    "security_id": 101,
                                    "last_price": 125,
                                    "greeks": {
                                        "gamma": 0.001,
                                    },
                                },
                            },
                        },
                    },
                },
            }

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhan()
    )

    snapshot = adapter.get_option_chain(
        OptionChainRequest(
            underlying_symbol="NIFTY 50",
            option_type=OptionType.CALL,
            reference_price=24500,
            requested_at=NOW,
            expiry=EXPIRY,
        )
    )

    assert snapshot.candidates == ()


def test_dhan_zero_ltp_is_skipped() -> None:
    class FakeDhan:
        def option_chain(
            self,
            *,
            under_security_id,
            under_exchange_segment,
            expiry,
        ):
            return {
                "status": "success",
                "remarks": "",
                "data": {
                    "status": "success",
                    "data": {
                        "last_price": 24500,
                        "oc": {
                            "24500.000000": {
                                "ce": {
                                    "security_id": 101,
                                    "last_price": 0,
                                    "greeks": {
                                        "delta": 0.64,
                                    },
                                },
                            },
                        },
                    },
                },
            }

    adapter = DhanOptionChainAdapter(
        dhan_client=FakeDhan()
    )

    snapshot = adapter.get_option_chain(
        OptionChainRequest(
            underlying_symbol="NIFTY 50",
            option_type=OptionType.CALL,
            reference_price=24500,
            requested_at=NOW,
            expiry=EXPIRY,
        )
    )

    assert snapshot.candidates == ()