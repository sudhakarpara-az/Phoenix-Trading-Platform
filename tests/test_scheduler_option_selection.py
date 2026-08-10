"""
Tests for Phoenix M10 09:16 CE/PE option selection.
"""

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
from src.services.scheduler import (
    TradingDayOptionSelectionCoordinator,
    TradingDayOptionSelectionError,
    TradingDayReferenceCoordinator,
    TradingDayScheduler,
    TradingDayState,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

EXPIRY = date(
    2026,
    8,
    13,
)

CREATED_AT = datetime(
    2026,
    8,
    10,
    8,
    30,
)

STARTED_AT = datetime(
    2026,
    8,
    10,
    9,
    0,
)

REFERENCE_OPEN_AT = datetime(
    2026,
    8,
    10,
    9,
    15,
)

SELECTION_AT = datetime(
    2026,
    8,
    10,
    9,
    16,
)


def make_scheduler() -> TradingDayScheduler:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT
    )

    TradingDayReferenceCoordinator(
        scheduler=scheduler
    ).begin_reference_window(
        opened_at=REFERENCE_OPEN_AT
    )

    return scheduler


def make_selected_option(
    *,
    option_type: OptionType,
    security_id: str,
    expiry: date = EXPIRY,
    underlying_symbol: str = "NIFTY 50",
) -> SelectedOption:
    side = (
        "CE"
        if option_type is OptionType.CALL
        else "PE"
    )

    delta = (
        0.60
        if option_type is OptionType.CALL
        else -0.60
    )

    candidate = OptionCandidate(
        contract=OptionContract(
            underlying_symbol=underlying_symbol,
            symbol=(
                f"NIFTY-{expiry.isoformat()}-"
                f"24500-{side}"
            ),
            security_id=security_id,
            option_type=option_type,
            strike=24500.0,
            expiry=expiry,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=100.0,
            received_at=SELECTION_AT,
        ),
        greeks=OptionGreeks(
            delta=delta,
            calculated_at=SELECTION_AT,
        ),
    )

    return SelectedOption(
        candidate=candidate,
        selected_at=SELECTION_AT,
        selection_delta_target=0.60,
    )


def selected_result(
    *,
    option_type: OptionType,
    security_id: str,
    expiry: date = EXPIRY,
    underlying_symbol: str = "NIFTY 50",
) -> OptionSelectionResult:
    return OptionSelectionResult(
        status=OptionSelectionStatus.SELECTED,
        selected_option=make_selected_option(
            option_type=option_type,
            security_id=security_id,
            expiry=expiry,
            underlying_symbol=underlying_symbol,
        ),
    )


def failed_result() -> OptionSelectionResult:
    return OptionSelectionResult(
        status=(
            OptionSelectionStatus.NO_DELTA_MATCH
        ),
        message="No delta match",
    )


class FakeSelectionService:
    def __init__(
        self,
        *,
        call_result: OptionSelectionResult,
        put_result: OptionSelectionResult,
    ) -> None:
        self.call_result = call_result
        self.put_result = put_result

        self.calls: list[
            tuple[
                OptionType,
                date,
                float,
                datetime,
                date | None,
            ]
        ] = []

    def select_for_option_type(
        self,
        *,
        option_type: OptionType,
        trading_date: date,
        reference_price: float,
        requested_at: datetime,
        requested_expiry: date | None = None,
    ) -> OptionSelectionResult:
        self.calls.append(
            (
                option_type,
                trading_date,
                reference_price,
                requested_at,
                requested_expiry,
            )
        )

        if option_type is OptionType.CALL:
            return self.call_result

        return self.put_result


def make_service() -> FakeSelectionService:
    return FakeSelectionService(
        call_result=selected_result(
            option_type=OptionType.CALL,
            security_id="CALL-101",
        ),
        put_result=selected_result(
            option_type=OptionType.PUT,
            security_id="PUT-201",
        ),
    )


def test_selection_cannot_begin_before_916() -> None:
    scheduler = make_scheduler()
    service = make_service()

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    with pytest.raises(
        TradingDayOptionSelectionError,
        match=(
            "option selection cannot begin before "
            "reference_candle_end"
        ),
    ):
        coordinator.select_options(
            reference_price=24500.0,
            requested_at=datetime(
                2026,
                8,
                10,
                9,
                15,
                59,
            ),
        )

    assert service.calls == []

    assert (
        scheduler.state
        is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
    )


def test_call_and_put_are_selected_independently() -> None:
    scheduler = make_scheduler()
    service = make_service()

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    result = coordinator.select_options(
        reference_price=24500.0,
        requested_at=SELECTION_AT,
    )

    assert result.is_complete is True

    assert result.selected_call is not None
    assert result.selected_put is not None

    assert (
        result.selected_call.option_type
        is OptionType.CALL
    )

    assert (
        result.selected_put.option_type
        is OptionType.PUT
    )

    assert (
        result.selected_call.security_id
        == "CALL-101"
    )

    assert (
        result.selected_put.security_id
        == "PUT-201"
    )

    assert [
        call[0]
        for call in service.calls
    ] == [
        OptionType.CALL,
        OptionType.PUT,
    ]

    assert (
        scheduler.state
        is TradingDayState.PREPARING_LEVELS
    )


def test_both_sides_use_same_reference_price() -> None:
    scheduler = make_scheduler()
    service = make_service()

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    coordinator.select_options(
        reference_price=24567.25,
        requested_at=SELECTION_AT,
    )

    assert [
        call[2]
        for call in service.calls
    ] == [
        24567.25,
        24567.25,
    ]


def test_requested_expiry_is_forwarded_to_both_sides() -> None:
    scheduler = make_scheduler()
    service = make_service()

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    coordinator.select_options(
        reference_price=24500.0,
        requested_at=SELECTION_AT,
        requested_expiry=EXPIRY,
    )

    assert [
        call[4]
        for call in service.calls
    ] == [
        EXPIRY,
        EXPIRY,
    ]


def test_partial_failure_remains_selecting_options() -> None:
    scheduler = make_scheduler()

    service = FakeSelectionService(
        call_result=selected_result(
            option_type=OptionType.CALL,
            security_id="CALL-101",
        ),
        put_result=failed_result(),
    )

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    result = coordinator.select_options(
        reference_price=24500.0,
        requested_at=SELECTION_AT,
    )

    assert result.is_complete is False

    assert (
        result.call_result.status
        is OptionSelectionStatus.SELECTED
    )

    assert (
        result.put_result.status
        is OptionSelectionStatus.NO_DELTA_MATCH
    )

    assert (
        scheduler.state
        is TradingDayState.SELECTING_OPTIONS
    )

    assert coordinator.completed_result is None


def test_failed_pair_can_be_retried_atomically() -> None:
    scheduler = make_scheduler()

    service = FakeSelectionService(
        call_result=selected_result(
            option_type=OptionType.CALL,
            security_id="CALL-101",
        ),
        put_result=failed_result(),
    )

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    first = coordinator.select_options(
        reference_price=24500.0,
        requested_at=SELECTION_AT,
    )

    assert first.is_complete is False

    service.put_result = selected_result(
        option_type=OptionType.PUT,
        security_id="PUT-201",
    )

    retry_at = datetime(
        2026,
        8,
        10,
        9,
        16,
        2,
    )

    second = coordinator.select_options(
        reference_price=24500.0,
        requested_at=retry_at,
    )

    assert second.is_complete is True

    assert len(service.calls) == 4

    assert [
        call[0]
        for call in service.calls
    ] == [
        OptionType.CALL,
        OptionType.PUT,
        OptionType.CALL,
        OptionType.PUT,
    ]

    assert (
        scheduler.state
        is TradingDayState.PREPARING_LEVELS
    )


def test_successful_pair_is_fixed_and_idempotent() -> None:
    scheduler = make_scheduler()
    service = make_service()

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    first = coordinator.select_options(
        reference_price=24500.0,
        requested_at=SELECTION_AT,
    )

    second = coordinator.select_options(
        reference_price=24600.0,
        requested_at=datetime(
            2026,
            8,
            10,
            9,
            17,
        ),
    )

    assert second is first
    assert len(service.calls) == 2

    assert (
        scheduler.state
        is TradingDayState.PREPARING_LEVELS
    )


def test_selected_pair_must_share_expiry() -> None:
    scheduler = make_scheduler()

    service = FakeSelectionService(
        call_result=selected_result(
            option_type=OptionType.CALL,
            security_id="CALL-101",
            expiry=EXPIRY,
        ),
        put_result=selected_result(
            option_type=OptionType.PUT,
            security_id="PUT-201",
            expiry=date(
                2026,
                8,
                20,
            ),
        ),
    )

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    with pytest.raises(
        TradingDayOptionSelectionError,
        match=(
            "selected CALL and PUT expiries "
            "do not match"
        ),
    ):
        coordinator.select_options(
            reference_price=24500.0,
            requested_at=SELECTION_AT,
        )

    assert (
        scheduler.state
        is TradingDayState.SELECTING_OPTIONS
    )

    assert coordinator.completed_result is None


def test_selected_pair_must_preserve_option_sides() -> None:
    scheduler = make_scheduler()

    service = FakeSelectionService(
        call_result=selected_result(
            option_type=OptionType.PUT,
            security_id="WRONG-101",
        ),
        put_result=selected_result(
            option_type=OptionType.PUT,
            security_id="PUT-201",
        ),
    )

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    with pytest.raises(
        TradingDayOptionSelectionError,
        match=(
            "CALL selection returned a "
            "non-CALL contract"
        ),
    ):
        coordinator.select_options(
            reference_price=24500.0,
            requested_at=SELECTION_AT,
        )

    assert (
        scheduler.state
        is TradingDayState.SELECTING_OPTIONS
    )


def test_selection_rejects_wrong_trading_date() -> None:
    scheduler = make_scheduler()
    service = make_service()

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    with pytest.raises(
        TradingDayOptionSelectionError,
        match=(
            "timestamp does not match scheduler "
            "trading_date"
        ),
    ):
        coordinator.select_options(
            reference_price=24500.0,
            requested_at=datetime(
                2026,
                8,
                11,
                9,
                16,
            ),
        )

    assert service.calls == []


@pytest.mark.parametrize(
    "reference_price",
    [
        0.0,
        -1.0,
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
    ],
)
def test_selection_rejects_invalid_reference_price(
    reference_price,
) -> None:
    scheduler = make_scheduler()
    service = make_service()

    coordinator = (
        TradingDayOptionSelectionCoordinator(
            scheduler=scheduler,
            selection_service=service,
        )
    )

    with pytest.raises(
        TradingDayOptionSelectionError,
        match=(
            "reference_price must be a finite number "
            "greater than zero"
        ),
    ):
        coordinator.select_options(
            reference_price=reference_price,
            requested_at=SELECTION_AT,
        )

    assert service.calls == []

    assert (
        scheduler.state
        is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
    )
