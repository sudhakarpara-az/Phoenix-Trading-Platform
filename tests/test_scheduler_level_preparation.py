"""
Tests for Phoenix M10 selected-contract reference-candle
and independent CE/PE KS readiness.
"""

from datetime import date, datetime

import pytest

from src.market.candle_builder import (
    HistoricalCandle,
)
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
    TradingDayLevelPreparationCoordinator,
    TradingDayLevelPreparationError,
    TradingDayOptionSelectionResult,
    TradingDayScheduler,
    TradingDayState,
)
from src.strategy.daily_ks_level_service import (
    DailyKSLevelService,
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

PREPARED_AT = datetime(
    2026,
    8,
    10,
    9,
    16,
    5,
)

CANDLE_START = datetime(
    2026,
    8,
    10,
    9,
    15,
)

CANDLE_END = datetime(
    2026,
    8,
    10,
    9,
    16,
)


def make_selected(
    *,
    option_type: OptionType,
    security_id: str,
    symbol: str,
) -> SelectedOption:
    delta = (
        0.60
        if option_type is OptionType.CALL
        else -0.60
    )

    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=symbol,
                security_id=security_id,
                option_type=option_type,
                strike=24500.0,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=100.0,
                received_at=PREPARED_AT,
            ),
            greeks=OptionGreeks(
                delta=delta,
                calculated_at=PREPARED_AT,
            ),
        ),
        selected_at=CANDLE_END,
        selection_delta_target=0.60,
    )


CALL = make_selected(
    option_type=OptionType.CALL,
    security_id="CALL-101",
    symbol="NIFTY-20260813-24500-CE",
)

PUT = make_selected(
    option_type=OptionType.PUT,
    security_id="PUT-201",
    symbol="NIFTY-20260813-24500-PE",
)


def selection_result(
    *,
    call: SelectedOption = CALL,
    put: SelectedOption = PUT,
) -> TradingDayOptionSelectionResult:
    return TradingDayOptionSelectionResult(
        call_result=OptionSelectionResult(
            status=OptionSelectionStatus.SELECTED,
            selected_option=call,
        ),
        put_result=OptionSelectionResult(
            status=OptionSelectionStatus.SELECTED,
            selected_option=put,
        ),
        attempted_at=CANDLE_END,
        completed_at=CANDLE_END,
    )


def make_scheduler() -> TradingDayScheduler:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=datetime(
            2026,
            8,
            10,
            9,
            0,
        )
    )

    scheduler.transition(
        target_state=(
            TradingDayState
            .WAITING_FOR_REFERENCE_CLOSE
        ),
        transitioned_at=datetime(
            2026,
            8,
            10,
            9,
            15,
        ),
    )

    scheduler.transition(
        target_state=(
            TradingDayState.SELECTING_OPTIONS
        ),
        transitioned_at=CANDLE_END,
    )

    scheduler.transition(
        target_state=(
            TradingDayState.PREPARING_LEVELS
        ),
        transitioned_at=CANDLE_END,
    )

    return scheduler


def make_candle(
    option: SelectedOption,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> HistoricalCandle:
    return HistoricalCandle(
        security_id=option.security_id,
        symbol=option.symbol,
        start_time=CANDLE_START,
        end_time=CANDLE_END,
        open=open_price,
        high=high,
        low=low,
        close=close,
    )


class FakeCandleProvider:
    def __init__(
        self,
        candles,
    ) -> None:
        self.candles = {
            candle.security_id: candle
            for candle in candles
        }

        self.calls = []

    def get_one_minute_candle(
        self,
        *,
        security_id,
        symbol,
        candle_start,
        requested_at,
    ):
        self.calls.append(
            (
                security_id,
                symbol,
                candle_start,
                requested_at,
            )
        )

        if security_id not in self.candles:
            raise RuntimeError(
                "reference candle unavailable"
            )

        return self.candles[
            security_id
        ]


def make_provider() -> FakeCandleProvider:
    return FakeCandleProvider(
        [
            make_candle(
                CALL,
                open_price=100.0,
                high=110.0,
                low=95.0,
                close=105.0,
            ),
            make_candle(
                PUT,
                open_price=120.0,
                high=128.0,
                low=114.0,
                close=122.0,
            ),
        ]
    )


def make_coordinator(
    scheduler,
    provider,
):
    return TradingDayLevelPreparationCoordinator(
        scheduler=scheduler,
        candle_provider=provider,
        call_level_service=DailyKSLevelService(),
        put_level_service=DailyKSLevelService(),
    )


def test_prepares_independent_call_and_put_levels() -> None:
    scheduler = make_scheduler()
    provider = make_provider()

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    result = coordinator.prepare_levels(
        selection=selection_result(),
        prepared_at=PREPARED_AT,
    )

    assert result.is_ready is True

    assert (
        result.call_levels.instrument_security_id
        == CALL.security_id
    )

    assert (
        result.put_levels.instrument_security_id
        == PUT.security_id
    )

    assert (
        result.call_levels.high_915
        == 110.0
    )

    assert (
        result.put_levels.high_915
        == 128.0
    )

    assert result.call_levels != result.put_levels

    assert (
        scheduler.state
        is TradingDayState.WAITING_FOR_MONITORING
    )


def test_selected_contracts_are_requested_independently() -> None:
    scheduler = make_scheduler()
    provider = make_provider()

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    coordinator.prepare_levels(
        selection=selection_result(),
        prepared_at=PREPARED_AT,
    )

    assert [
        call[0]
        for call in provider.calls
    ] == [
        CALL.security_id,
        PUT.security_id,
    ]

    assert all(
        call[2] == CANDLE_START
        for call in provider.calls
    )


def test_missing_put_candle_remains_fail_closed() -> None:
    scheduler = make_scheduler()

    provider = FakeCandleProvider(
        [
            make_candle(
                CALL,
                open_price=100.0,
                high=110.0,
                low=95.0,
                close=105.0,
            )
        ]
    )

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    with pytest.raises(
        RuntimeError,
        match="reference candle unavailable",
    ):
        coordinator.prepare_levels(
            selection=selection_result(),
            prepared_at=PREPARED_AT,
        )

    assert (
        scheduler.state
        is TradingDayState.PREPARING_LEVELS
    )

    assert coordinator.completed_result is None


def test_incomplete_selection_is_rejected() -> None:
    scheduler = make_scheduler()
    provider = make_provider()

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    incomplete = TradingDayOptionSelectionResult(
        call_result=OptionSelectionResult(
            status=OptionSelectionStatus.SELECTED,
            selected_option=CALL,
        ),
        put_result=OptionSelectionResult(
            status=OptionSelectionStatus.NO_DELTA_MATCH,
            message="No PUT",
        ),
        attempted_at=CANDLE_END,
    )

    with pytest.raises(
        TradingDayLevelPreparationError,
        match="completed CE/PE option selection is required",
    ):
        coordinator.prepare_levels(
            selection=incomplete,
            prepared_at=PREPARED_AT,
        )

    assert provider.calls == []


def test_wrong_call_candle_identity_is_rejected() -> None:
    scheduler = make_scheduler()

    wrong_call = HistoricalCandle(
        security_id="WRONG",
        symbol=CALL.symbol,
        start_time=CANDLE_START,
        end_time=CANDLE_END,
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
    )

    provider = FakeCandleProvider(
        [
            wrong_call,
            make_candle(
                PUT,
                open_price=120.0,
                high=128.0,
                low=114.0,
                close=122.0,
            ),
        ]
    )

    provider.candles[
        CALL.security_id
    ] = wrong_call

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    with pytest.raises(
        TradingDayLevelPreparationError,
        match="security ID does not match selected option",
    ):
        coordinator.prepare_levels(
            selection=selection_result(),
            prepared_at=PREPARED_AT,
        )

    assert (
        scheduler.state
        is TradingDayState.PREPARING_LEVELS
    )


def test_wrong_reference_window_is_rejected() -> None:
    scheduler = make_scheduler()

    bad = HistoricalCandle(
        security_id=CALL.security_id,
        symbol=CALL.symbol,
        start_time=datetime(
            2026,
            8,
            10,
            9,
            14,
        ),
        end_time=datetime(
            2026,
            8,
            10,
            9,
            15,
        ),
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
    )

    provider = make_provider()
    provider.candles[
        CALL.security_id
    ] = bad

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    with pytest.raises(
        TradingDayLevelPreparationError,
        match="does not start at 09:15",
    ):
        coordinator.prepare_levels(
            selection=selection_result(),
            prepared_at=PREPARED_AT,
        )

    assert (
        scheduler.state
        is TradingDayState.PREPARING_LEVELS
    )


def test_successful_preparation_is_idempotent() -> None:
    scheduler = make_scheduler()
    provider = make_provider()

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    first = coordinator.prepare_levels(
        selection=selection_result(),
        prepared_at=PREPARED_AT,
    )

    second = coordinator.prepare_levels(
        selection=selection_result(),
        prepared_at=datetime(
            2026,
            8,
            10,
            9,
            17,
        ),
    )

    assert second is first
    assert len(provider.calls) == 2


def test_different_pair_cannot_replace_fixed_levels() -> None:
    scheduler = make_scheduler()
    provider = make_provider()

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    coordinator.prepare_levels(
        selection=selection_result(),
        prepared_at=PREPARED_AT,
    )

    other_call = make_selected(
        option_type=OptionType.CALL,
        security_id="CALL-999",
        symbol="NIFTY-OTHER-CE",
    )

    with pytest.raises(
        TradingDayLevelPreparationError,
        match="already fixed for another selected option pair",
    ):
        coordinator.prepare_levels(
            selection=selection_result(
                call=other_call,
            ),
            prepared_at=datetime(
                2026,
                8,
                10,
                9,
                17,
            ),
        )


def test_shared_level_service_is_rejected() -> None:
    service = DailyKSLevelService()

    with pytest.raises(
        ValueError,
        match=(
            "CALL and PUT must use separate "
            "DailyKSLevelService instances"
        ),
    ):
        TradingDayLevelPreparationCoordinator(
            scheduler=make_scheduler(),
            candle_provider=make_provider(),
            call_level_service=service,
            put_level_service=service,
        )


def test_level_preparation_rejects_wrong_date() -> None:
    scheduler = make_scheduler()
    provider = make_provider()

    coordinator = make_coordinator(
        scheduler,
        provider,
    )

    with pytest.raises(
        TradingDayLevelPreparationError,
        match=(
            "timestamp does not match scheduler "
            "trading_date"
        ),
    ):
        coordinator.prepare_levels(
            selection=selection_result(),
            prepared_at=datetime(
                2026,
                8,
                11,
                9,
                16,
            ),
        )

    assert provider.calls == []


def test_level_preparation_requires_preparing_state() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=datetime(
            2026,
            8,
            10,
            9,
            0,
        )
    )

    coordinator = make_coordinator(
        scheduler,
        make_provider(),
    )

    with pytest.raises(
        TradingDayLevelPreparationError,
        match="requires PREPARING_LEVELS state",
    ):
        coordinator.prepare_levels(
            selection=selection_result(),
            prepared_at=PREPARED_AT,
        )
