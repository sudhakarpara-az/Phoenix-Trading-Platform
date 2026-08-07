from datetime import date, datetime, timedelta

import pytest

from src.option_selection.option_chain_cache import (
    OptionChainCache,
    OptionChainCacheKey,
    OptionChainFreshnessConfig,
    OptionChainFreshnessGuard,
)
from src.option_selection.option_chain_provider import (
    OptionChainSnapshot,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
)


EXPIRY = date(
    2026,
    8,
    13,
)

NOW = datetime(
    2026,
    8,
    7,
    10,
    0,
    5,
)


def make_candidate(
    *,
    quote_time: datetime,
    greeks_time: datetime | None,
) -> OptionCandidate:
    return OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol="NIFTY-24500-CE",
            security_id="101",
            option_type=OptionType.CALL,
            strike=24500,
            expiry=EXPIRY,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=125.0,
            bid=124.0,
            ask=126.0,
            volume=1000,
            open_interest=50000,
            received_at=quote_time,
        ),
        greeks=OptionGreeks(
            delta=0.64,
            gamma=0.001,
            theta=-4.0,
            vega=6.0,
            implied_volatility=12.0,
            calculated_at=greeks_time,
        ),
    )


def make_snapshot(
    *,
    snapshot_time: datetime,
    quote_time: datetime | None = None,
    greeks_time: datetime | None = None,
) -> OptionChainSnapshot:
    quote_time = (
        quote_time
        if quote_time is not None
        else snapshot_time
    )

    greeks_time = (
        greeks_time
        if greeks_time is not None
        else snapshot_time
    )

    candidate = make_candidate(
        quote_time=quote_time,
        greeks_time=greeks_time,
    )

    return OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=snapshot_time,
        provider_name="TEST",
    )


def make_key() -> OptionChainCacheKey:
    return OptionChainCacheKey(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.CALL,
        expiry=EXPIRY,
    )


def make_guard() -> OptionChainFreshnessGuard:
    return OptionChainFreshnessGuard(
        OptionChainFreshnessConfig(
            snapshot_max_age_seconds=3,
            quote_max_age_seconds=3,
            greeks_max_age_seconds=3,
        )
    )


def test_default_freshness_configuration() -> None:
    config = OptionChainFreshnessConfig()

    assert (
        config.snapshot_max_age_seconds
        == 3.0
    )

    assert (
        config.quote_max_age_seconds
        == 3.0
    )

    assert (
        config.greeks_max_age_seconds
        == 3.0
    )


def test_invalid_snapshot_age_configuration_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "snapshot_max_age_seconds "
            "must be greater than zero"
        ),
    ):
        OptionChainFreshnessConfig(
            snapshot_max_age_seconds=0,
        )


def test_fresh_snapshot_is_accepted() -> None:
    guard = make_guard()

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(seconds=1)
        )
    )

    result = guard.evaluate(
        snapshot,
        NOW,
    )

    assert result.fresh is True
    assert result.snapshot_fresh is True
    assert result.quotes_fresh is True
    assert result.greeks_fresh is True
    assert result.stale_candidate_count == 0


def test_snapshot_at_age_boundary_is_fresh() -> None:
    guard = make_guard()

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(seconds=3)
        )
    )

    assert guard.is_fresh(
        snapshot,
        NOW,
    ) is True


def test_stale_snapshot_is_rejected() -> None:
    guard = make_guard()

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(
                seconds=4
            )
        )
    )

    result = guard.evaluate(
        snapshot,
        NOW,
    )

    assert result.fresh is False
    assert result.snapshot_fresh is False


def test_stale_quote_is_rejected() -> None:
    guard = make_guard()

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(seconds=1)
        ),
        quote_time=(
            NOW
            - timedelta(seconds=4)
        ),
        greeks_time=(
            NOW
            - timedelta(seconds=1)
        ),
    )

    result = guard.evaluate(
        snapshot,
        NOW,
    )

    assert result.fresh is False
    assert result.quotes_fresh is False
    assert result.greeks_fresh is True


def test_stale_greeks_are_rejected() -> None:
    guard = make_guard()

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(seconds=1)
        ),
        quote_time=(
            NOW
            - timedelta(seconds=1)
        ),
        greeks_time=(
            NOW
            - timedelta(seconds=4)
        ),
    )

    result = guard.evaluate(
        snapshot,
        NOW,
    )

    assert result.fresh is False
    assert result.greeks_fresh is False


def test_future_snapshot_is_rejected() -> None:
    guard = make_guard()

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            + timedelta(seconds=1)
        )
    )

    assert guard.is_fresh(
        snapshot,
        NOW,
    ) is False


def test_missing_greeks_timestamp_is_stale() -> None:
    candidate = make_candidate(
        quote_time=NOW,
        greeks_time=None,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=NOW,
        provider_name="TEST",
    )

    result = make_guard().evaluate(
        snapshot,
        NOW,
    )

    assert result.fresh is False
    assert result.greeks_fresh is False


def test_filter_fresh_candidates_removes_stale_candidate() -> None:
    fresh = make_candidate(
        quote_time=(
            NOW
            - timedelta(seconds=1)
        ),
        greeks_time=(
            NOW
            - timedelta(seconds=1)
        ),
    )

    stale = make_candidate(
        quote_time=(
            NOW
            - timedelta(seconds=10)
        ),
        greeks_time=(
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
        provider_name="TEST",
    )

    result = (
        make_guard()
        .filter_fresh_candidates(
            snapshot,
            NOW,
        )
    )

    assert result == (
        fresh,
    )


def test_cache_starts_empty() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    assert cache.count() == 0
    assert cache.get(make_key()) is None


def test_cache_put_and_get() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    snapshot = make_snapshot(
        snapshot_time=NOW
    )

    key = make_key()

    cache.put(
        key,
        snapshot,
    )

    assert cache.count() == 1
    assert cache.get(key) is snapshot


def test_get_fresh_returns_fresh_snapshot() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(seconds=1)
        )
    )

    key = make_key()

    cache.put(
        key,
        snapshot,
    )

    assert (
        cache.get_fresh(
            key,
            NOW,
        )
        is snapshot
    )


def test_get_fresh_returns_none_for_stale_snapshot() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(seconds=10)
        )
    )

    key = make_key()

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


def test_stale_snapshot_remains_available_for_diagnostics() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    snapshot = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(seconds=10)
        )
    )

    key = make_key()

    cache.put(
        key,
        snapshot,
    )

    assert cache.get(key) is snapshot

    assert (
        cache.get_fresh(
            key,
            NOW,
        )
        is None
    )


def test_cache_replaces_existing_snapshot() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    key = make_key()

    old = make_snapshot(
        snapshot_time=(
            NOW
            - timedelta(seconds=10)
        )
    )

    new = make_snapshot(
        snapshot_time=NOW
    )

    cache.put(
        key,
        old,
    )

    cache.put(
        key,
        new,
    )

    assert cache.count() == 1
    assert cache.get(key) is new


def test_remove_snapshot() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    key = make_key()

    cache.put(
        key,
        make_snapshot(
            snapshot_time=NOW
        ),
    )

    assert cache.remove(key) is True
    assert cache.count() == 0


def test_remove_unknown_snapshot_returns_false() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    assert (
        cache.remove(
            make_key()
        )
        is False
    )


def test_clear_returns_removed_count() -> None:
    cache = OptionChainCache(
        freshness_guard=make_guard()
    )

    call_key = make_key()

    put_key = OptionChainCacheKey(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.PUT,
        expiry=EXPIRY,
    )

    snapshot = make_snapshot(
        snapshot_time=NOW
    )

    cache.put(
        call_key,
        snapshot,
    )

    cache.put(
        put_key,
        snapshot,
    )

    removed = cache.clear()

    assert removed == 2
    assert cache.count() == 0


def test_empty_cache_underlying_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="underlying_symbol cannot be empty",
    ):
        OptionChainCacheKey(
            underlying_symbol=" ",
            option_type=OptionType.CALL,
            expiry=EXPIRY,
        )