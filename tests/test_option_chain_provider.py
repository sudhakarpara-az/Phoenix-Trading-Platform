from datetime import date, datetime

import pytest

from src.option_selection.option_chain_provider import (
    OptionChainProvider,
    OptionChainRequest,
    OptionChainSnapshot,
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
    option_type: OptionType,
    strike: float,
    delta: float,
) -> OptionCandidate:
    contract = OptionContract(
        underlying_symbol="NIFTY 50",
        symbol=(
            f"NIFTY-{int(strike)}-"
            f"{option_type.value}"
        ),
        security_id=security_id,
        option_type=option_type,
        strike=strike,
        expiry=EXPIRY,
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


class FakeOptionChainProvider(
    OptionChainProvider
):
    """
    Test implementation of the provider interface.
    """

    def __init__(
        self,
        candidates: tuple[
            OptionCandidate,
            ...
        ],
    ) -> None:
        self._candidates = candidates
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


def test_option_chain_request_creation() -> None:
    request = OptionChainRequest(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.CALL,
        reference_price=24500.0,
        requested_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )

    assert (
        request.underlying_symbol
        == "NIFTY 50"
    )

    assert (
        request.option_type
        is OptionType.CALL
    )

    assert (
        request.reference_price
        == 24500.0
    )

    assert request.expiry is None


def test_request_can_include_expiry() -> None:
    request = OptionChainRequest(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.PUT,
        reference_price=24500.0,
        requested_at=datetime.now(),
        expiry=EXPIRY,
    )

    assert request.expiry == EXPIRY


def test_empty_underlying_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="underlying_symbol cannot be empty",
    ):
        OptionChainRequest(
            underlying_symbol=" ",
            option_type=OptionType.CALL,
            reference_price=24500.0,
            requested_at=datetime.now(),
        )


def test_invalid_reference_price_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="reference_price must be greater than zero",
    ):
        OptionChainRequest(
            underlying_symbol="NIFTY 50",
            option_type=OptionType.CALL,
            reference_price=0,
            requested_at=datetime.now(),
        )


def test_snapshot_creation() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=datetime.now(),
        provider_name="FAKE",
    )

    assert snapshot.count() == 1
    assert snapshot.is_empty() is False


def test_empty_snapshot() -> None:
    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(),
        received_at=datetime.now(),
        provider_name="FAKE",
    )

    assert snapshot.count() == 0
    assert snapshot.is_empty() is True


def test_snapshot_filters_call_options() -> None:
    call = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    put = make_candidate(
        security_id="102",
        option_type=OptionType.PUT,
        strike=24500,
        delta=-0.64,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(
            call,
            put,
        ),
        received_at=datetime.now(),
        provider_name="FAKE",
    )

    results = snapshot.by_option_type(
        OptionType.CALL
    )

    assert results == (call,)


def test_snapshot_filters_put_options() -> None:
    call = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    put = make_candidate(
        security_id="102",
        option_type=OptionType.PUT,
        strike=24500,
        delta=-0.64,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(
            call,
            put,
        ),
        received_at=datetime.now(),
        provider_name="FAKE",
    )

    results = snapshot.by_option_type(
        OptionType.PUT
    )

    assert results == (put,)


def test_snapshot_filters_expiry() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=datetime.now(),
        provider_name="FAKE",
    )

    assert snapshot.by_expiry(
        EXPIRY
    ) == (candidate,)


def test_snapshot_unknown_expiry_returns_empty() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    snapshot = OptionChainSnapshot(
        underlying_symbol="NIFTY 50",
        reference_price=24500,
        candidates=(candidate,),
        received_at=datetime.now(),
        provider_name="FAKE",
    )

    assert snapshot.by_expiry(
        date(2026, 8, 20)
    ) == ()


def test_empty_provider_name_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="provider_name cannot be empty",
    ):
        OptionChainSnapshot(
            underlying_symbol="NIFTY 50",
            reference_price=24500,
            candidates=(),
            received_at=datetime.now(),
            provider_name=" ",
        )


def test_fake_provider_implements_interface() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    provider = FakeOptionChainProvider(
        candidates=(candidate,)
    )

    assert isinstance(
        provider,
        OptionChainProvider,
    )


def test_provider_returns_snapshot() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    provider = FakeOptionChainProvider(
        candidates=(candidate,)
    )

    request = OptionChainRequest(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.CALL,
        reference_price=24500,
        requested_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )

    snapshot = provider.get_option_chain(
        request
    )

    assert (
        snapshot.provider_name
        == "FAKE"
    )

    assert snapshot.count() == 1

    assert (
        provider.last_request
        is request
    )


def test_provider_preserves_request_reference_price() -> None:
    provider = FakeOptionChainProvider(
        candidates=()
    )

    request = OptionChainRequest(
        underlying_symbol="NIFTY 50",
        option_type=OptionType.PUT,
        reference_price=24625.75,
        requested_at=datetime.now(),
    )

    snapshot = provider.get_option_chain(
        request
    )

    assert (
        snapshot.reference_price
        == 24625.75
    )