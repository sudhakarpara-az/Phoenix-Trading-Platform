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
EXPIRY = date(2026, 8, 13)


def make_candidate(
    *,
    security_id: str,
    option_type: OptionType,
    strike: float,
    delta: float,
) -> OptionCandidate:
    return OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol=f"NIFTY-{security_id}",
            security_id=security_id,
            option_type=option_type,
            strike=strike,
            expiry=EXPIRY,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=125.0,
            bid=124.0,
            ask=126.0,
            volume=1000,
            open_interest=50000,
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


class FakeProvider(
    OptionChainProvider
):
    def __init__(
        self,
        candidates: tuple[
            OptionCandidate,
            ...
        ],
        should_fail: bool = False,
    ) -> None:
        self._candidates = candidates
        self._should_fail = should_fail

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

        if self._should_fail:
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


def make_signal(
    *,
    direction: SignalDirection,
    underlying_symbol: str = "NIFTY 50",
    underlying_price: float = 24500.0,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-20260807-K5-000001"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=direction,
        underlying_symbol=underlying_symbol,
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


def test_select_for_option_type_selects_call_without_signal() -> None:
    call = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.60,
    )

    put = make_candidate(
        security_id="201",
        option_type=OptionType.PUT,
        strike=24500,
        delta=-0.60,
    )

    provider = FakeProvider(
        candidates=(
            put,
            call,
        )
    )

    service = OptionSelectionService(
        provider=provider,
        selector=make_selector(),
    )

    requested_at = datetime(
        2026,
        8,
        7,
        9,
        16,
        1,
    )

    result = service.select_for_option_type(
        option_type=OptionType.CALL,
        trading_date=EXPIRY.replace(day=7),
        reference_price=24500.0,
        requested_at=requested_at,
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

    assert provider.last_request is not None

    assert (
        provider.last_request.option_type
        is OptionType.CALL
    )


def test_call_and_put_can_be_selected_independently_before_signal() -> None:
    call = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.60,
    )

    put = make_candidate(
        security_id="201",
        option_type=OptionType.PUT,
        strike=24600,
        delta=-0.60,
    )

    service = OptionSelectionService(
        provider=FakeProvider(
            candidates=(
                call,
                put,
            )
        ),
        selector=make_selector(),
    )

    requested_at = datetime(
        2026,
        8,
        7,
        9,
        16,
        1,
    )

    trading_date = requested_at.date()

    call_result = service.select_for_option_type(
        option_type=OptionType.CALL,
        trading_date=trading_date,
        reference_price=24500.0,
        requested_at=requested_at,
    )

    put_result = service.select_for_option_type(
        option_type=OptionType.PUT,
        trading_date=trading_date,
        reference_price=24500.0,
        requested_at=requested_at,
    )

    assert call_result.selected_option is not None
    assert put_result.selected_option is not None

    assert (
        call_result.selected_option.option_type
        is OptionType.CALL
    )

    assert (
        put_result.selected_option.option_type
        is OptionType.PUT
    )

    assert (
        call_result.selected_option.security_id
        != put_result.selected_option.security_id
    )

    assert (
        call_result.selected_option.selection_delta_target
        == 0.60
    )

    assert (
        put_result.selected_option.selection_delta_target
        == 0.60
    )



def test_call_signal_maps_to_call_option() -> None:
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

    service = OptionSelectionService(
        provider=provider,
        selector=make_selector(),
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=datetime(
            2026,
            8,
            7,
            10,
            0,
            1,
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


def test_put_signal_maps_to_put_option() -> None:
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

    service = OptionSelectionService(
        provider=provider,
        selector=make_selector(),
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.PUT
        ),
        requested_at=datetime(
            2026,
            8,
            7,
            10,
            0,
            1,
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


def test_service_builds_provider_request() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    provider = FakeProvider(
        candidates=(candidate,)
    )

    service = OptionSelectionService(
        provider=provider,
        selector=make_selector(),
    )

    requested_at = datetime(
        2026,
        8,
        7,
        10,
        0,
        1,
    )

    service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL,
            underlying_price=24625.50,
        ),
        requested_at=requested_at,
    )

    assert provider.last_request is not None

    assert (
        provider.last_request.option_type
        is OptionType.CALL
    )

    assert (
        provider.last_request.reference_price
        == 24625.50
    )

    assert (
        provider.last_request.requested_at
        == requested_at
    )


def test_requested_expiry_is_forwarded() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    provider = FakeProvider(
        candidates=(candidate,)
    )

    service = OptionSelectionService(
        provider=provider,
        selector=make_selector(),
    )

    service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=datetime.now(),
        requested_expiry=EXPIRY,
    )

    assert provider.last_request is not None
    assert provider.last_request.expiry == EXPIRY


def test_best_delta_candidate_is_selected() -> None:
    delta_60 = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24400,
        delta=0.60,
    )

    delta_64 = make_candidate(
        security_id="102",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    delta_68 = make_candidate(
        security_id="103",
        option_type=OptionType.CALL,
        strike=24600,
        delta=0.68,
    )

    service = OptionSelectionService(
        provider=FakeProvider(
            candidates=(
                delta_60,
                delta_68,
                delta_64,
            )
        ),
        selector=make_selector(),
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=datetime.now(),
    )

    assert result.selected_option is not None

    assert (
        result.selected_option.security_id
        == "101"
    )


def test_out_of_range_candidates_return_no_delta_match() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.75,
    )

    service = OptionSelectionService(
        provider=FakeProvider(
            candidates=(candidate,)
        ),
        selector=make_selector(),
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=datetime.now(),
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_DELTA_MATCH
    )


def test_empty_provider_snapshot_returns_no_contracts() -> None:
    service = OptionSelectionService(
        provider=FakeProvider(
            candidates=()
        ),
        selector=make_selector(),
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=datetime.now(),
    )

    assert (
        result.status
        is OptionSelectionStatus.NO_CONTRACTS
    )


def test_provider_failure_returns_provider_error() -> None:
    service = OptionSelectionService(
        provider=FakeProvider(
            candidates=(),
            should_fail=True,
        ),
        selector=make_selector(),
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=datetime.now(),
    )

    assert (
        result.status
        is OptionSelectionStatus.PROVIDER_ERROR
    )

    assert result.selected_option is None


def test_unsupported_underlying_is_rejected() -> None:
    service = OptionSelectionService(
        provider=FakeProvider(
            candidates=()
        ),
        selector=make_selector(),
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL,
            underlying_symbol="BANKNIFTY",
        ),
        requested_at=datetime.now(),
    )

    assert (
        result.status
        is OptionSelectionStatus.INVALID_REQUEST
    )


def test_service_preserves_selected_lot_size() -> None:
    candidate = make_candidate(
        security_id="101",
        option_type=OptionType.CALL,
        strike=24500,
        delta=0.64,
    )

    service = OptionSelectionService(
        provider=FakeProvider(
            candidates=(candidate,)
        ),
        selector=make_selector(),
    )

    result = service.select_for_signal(
        signal=make_signal(
            direction=SignalDirection.CALL
        ),
        requested_at=datetime.now(),
    )

    assert result.selected_option is not None
    assert result.selected_option.lot_size == 65


def test_empty_supported_underlying_is_rejected() -> None:
    try:
        OptionSelectionService(
            provider=FakeProvider(
                candidates=()
            ),
            selector=make_selector(),
            supported_underlying=" ",
        )

        assert False, "Expected ValueError"

    except ValueError as exc:
        assert (
            str(exc)
            == "supported_underlying cannot be empty"
        )