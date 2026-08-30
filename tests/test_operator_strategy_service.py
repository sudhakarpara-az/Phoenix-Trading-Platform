from __future__ import annotations

from datetime import date
from datetime import datetime

import pytest

from src.api.operator_strategy import (
    OperatorStrategyService,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.services.scheduler import (
    TradingDayLevelPreparationResult,
)
from src.strategy.strategy_types import (
    KSLevels,
    ReferenceCandle,
)


TRADING_DATE = date(
    2026,
    8,
    31,
)

EXPIRY = date(
    2026,
    9,
    3,
)

NOW = datetime(
    2026,
    8,
    31,
    9,
    16,
)

CAPTURED_AT = datetime(
    2026,
    8,
    31,
    9,
    20,
)


def make_selected(
    *,
    option_type: OptionType,
    symbol: str,
    security_id: str,
    strike: float,
    delta: float,
    ltp: float,
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY",
                symbol=symbol,
                security_id=security_id,
                option_type=option_type,
                strike=strike,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=ltp,
                received_at=NOW,
                bid=None,
                ask=None,
                volume=None,
                open_interest=None,
            ),
            greeks=OptionGreeks(
                delta=delta,
                gamma=None,
                theta=None,
                vega=None,
                implied_volatility=None,
                calculated_at=NOW,
            ),
        ),
        selected_at=NOW,
        selection_delta_target=0.60,
    )


def make_candle(
    selected: SelectedOption,
) -> ReferenceCandle:
    return ReferenceCandle(
        trading_date=TRADING_DATE,
        instrument_security_id=(
            selected.security_id
        ),
        instrument_symbol=(
            selected.symbol
        ),
        start_time=datetime(
            2026,
            8,
            31,
            9,
            15,
        ),
        end_time=NOW,
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
    )


def make_levels(
    selected: SelectedOption,
    base: float,
) -> KSLevels:
    return KSLevels(
        trading_date=TRADING_DATE,
        instrument_security_id=(
            selected.security_id
        ),
        instrument_symbol=(
            selected.symbol
        ),
        high_915=110.0,
        low_915=95.0,
        close_915=105.0,
        n1=1.0,
        n2=2.0,
        c1=3.0,
        e_level=base + 1.0,
        t_level=base + 2.0,
        k0=base,
        k1=base + 1.0,
        k2=base + 2.0,
        k3=base + 3.0,
        k5=base + 5.0,
        k6=base + 6.0,
        k7=base + 7.0,
        calculated_at=NOW,
        formula_version="test-v1",
    )


class FakeSignalRuntime:
    def __init__(
        self,
        call: SelectedOption,
        put: SelectedOption,
    ) -> None:
        self._call = call
        self._put = put

    @property
    def selected_call(
        self,
    ) -> SelectedOption:
        return self._call

    @property
    def selected_put(
        self,
    ) -> SelectedOption:
        return self._put


class FakeEntryRuntime:
    def __init__(
        self,
        preparation:
            TradingDayLevelPreparationResult,
    ) -> None:
        self._preparation = preparation

    @property
    def level_preparation(
        self,
    ) -> TradingDayLevelPreparationResult:
        return self._preparation


def build_graph() -> tuple[
    SelectedOption,
    SelectedOption,
    TradingDayLevelPreparationResult,
    FakeSignalRuntime,
    FakeEntryRuntime,
]:
    call = make_selected(
        option_type=OptionType.CALL,
        symbol="NIFTY-CALL",
        security_id="CALL-1",
        strike=25000.0,
        delta=0.61,
        ltp=101.0,
    )

    put = make_selected(
        option_type=OptionType.PUT,
        symbol="NIFTY-PUT",
        security_id="PUT-1",
        strike=25000.0,
        delta=-0.62,
        ltp=99.0,
    )

    preparation = (
        TradingDayLevelPreparationResult(
            selected_call=call,
            selected_put=put,
            call_reference_candle=(
                make_candle(call)
            ),
            put_reference_candle=(
                make_candle(put)
            ),
            call_levels=(
                make_levels(
                    call,
                    100.0,
                )
            ),
            put_levels=(
                make_levels(
                    put,
                    200.0,
                )
            ),
            prepared_at=NOW,
        )
    )

    signal_runtime = (
        FakeSignalRuntime(
            call,
            put,
        )
    )

    entry_runtime = (
        FakeEntryRuntime(
            preparation
        )
    )

    return (
        call,
        put,
        preparation,
        signal_runtime,
        entry_runtime,
    )


def test_capture_maps_exact_prepared_state() -> None:
    (
        call,
        put,
        preparation,
        signal_runtime,
        entry_runtime,
    ) = build_graph()

    service = OperatorStrategyService(
        signal_runtime=signal_runtime,
        entry_runtime=entry_runtime,
    )

    view = service.capture(
        captured_at=CAPTURED_AT,
    )

    assert (
        service.signal_runtime
        is signal_runtime
    )

    assert (
        service.entry_runtime
        is entry_runtime
    )

    assert (
        preparation.selected_call
        is call
    )

    assert (
        preparation.selected_put
        is put
    )

    assert (
        view.trading_date
        == TRADING_DATE
    )

    assert view.expiry == EXPIRY

    assert (
        view.selected_call.symbol
        == "NIFTY-CALL"
    )

    assert (
        view.selected_call.option_type
        == "CALL"
    )

    assert (
        view.selected_call.delta
        == pytest.approx(0.61)
    )

    assert (
        view.selected_call
        .delta_magnitude
        == pytest.approx(0.61)
    )

    assert (
        view.selected_put.option_type
        == "PUT"
    )

    assert (
        view.selected_put.delta
        == pytest.approx(-0.62)
    )

    assert (
        view.selected_put
        .delta_magnitude
        == pytest.approx(0.62)
    )

    assert (
        view.call_levels.k5
        == pytest.approx(105.0)
    )

    assert (
        view.call_levels.k7
        == pytest.approx(107.0)
    )

    assert (
        view.put_levels.k5
        == pytest.approx(205.0)
    )

    assert (
        view.put_levels.k7
        == pytest.approx(207.0)
    )

    assert (
        view.prepared_at
        == NOW
    )

    assert (
        view.captured_at
        == CAPTURED_AT
    )

    assert view.is_ready is True


def test_capture_rejects_non_datetime() -> None:
    (
        _,
        _,
        _,
        signal_runtime,
        entry_runtime,
    ) = build_graph()

    service = OperatorStrategyService(
        signal_runtime=signal_runtime,
        entry_runtime=entry_runtime,
    )

    with pytest.raises(
        TypeError,
        match="captured_at must be datetime",
    ):
        service.capture(
            captured_at="bad",  # type: ignore[arg-type]
        )


def test_capture_rejects_different_call_instance() -> None:
    (
        _,
        put,
        preparation,
        _,
        entry_runtime,
    ) = build_graph()

    other_call = make_selected(
        option_type=OptionType.CALL,
        symbol="OTHER-CALL",
        security_id="CALL-OTHER",
        strike=25100.0,
        delta=0.60,
        ltp=102.0,
    )

    assert (
        preparation.selected_call
        is not other_call
    )

    service = OperatorStrategyService(
        signal_runtime=(
            FakeSignalRuntime(
                other_call,
                put,
            )
        ),
        entry_runtime=entry_runtime,
    )

    with pytest.raises(
        ValueError,
        match="exact prepared CALL",
    ):
        service.capture(
            captured_at=CAPTURED_AT,
        )


def test_capture_rejects_different_put_instance() -> None:
    (
        call,
        _,
        preparation,
        _,
        entry_runtime,
    ) = build_graph()

    other_put = make_selected(
        option_type=OptionType.PUT,
        symbol="OTHER-PUT",
        security_id="PUT-OTHER",
        strike=24900.0,
        delta=-0.60,
        ltp=98.0,
    )

    assert (
        preparation.selected_put
        is not other_put
    )

    service = OperatorStrategyService(
        signal_runtime=(
            FakeSignalRuntime(
                call,
                other_put,
            )
        ),
        entry_runtime=entry_runtime,
    )

    with pytest.raises(
        ValueError,
        match="exact prepared PUT",
    ):
        service.capture(
            captured_at=CAPTURED_AT,
        )
