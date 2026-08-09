from datetime import datetime, time

import pytest

from src.market.market_types import (
    Exchange,
    MarketTick,
)
from src.strategy.reference_candle_builder import (
    ReferenceCandleBuilder,
)


INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"


def make_builder() -> ReferenceCandleBuilder:
    return ReferenceCandleBuilder(
        security_id=INSTRUMENT_SECURITY_ID,
        instrument_symbol=INSTRUMENT_SYMBOL,
    )


def tick(
    price: float,
    hour: int,
    minute: int,
    second: int = 0,
    security_id: str = INSTRUMENT_SECURITY_ID,
    symbol: str = INSTRUMENT_SYMBOL,
    day: int = 7,
) -> MarketTick:
    return MarketTick(
        exchange=Exchange.NSE,
        symbol=symbol,
        security_id=security_id,
        ltp=price,
        volume=0,
        timestamp=datetime(
            2026,
            8,
            day,
            hour,
            minute,
            second,
        ),
    )


def test_builder_preserves_instrument_configuration() -> None:
    builder = make_builder()

    assert (
        builder.security_id
        == INSTRUMENT_SECURITY_ID
    )

    assert (
        builder.instrument_symbol
        == INSTRUMENT_SYMBOL
    )


def test_default_reference_window_is_915_to_916() -> None:
    builder = make_builder()

    assert builder.window_start == time(9, 15)
    assert builder.window_end == time(9, 16)


def test_empty_security_id_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="security_id cannot be empty",
    ):
        ReferenceCandleBuilder(
            security_id=" ",
            instrument_symbol=INSTRUMENT_SYMBOL,
        )


def test_empty_instrument_symbol_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="instrument_symbol cannot be empty",
    ):
        ReferenceCandleBuilder(
            security_id=INSTRUMENT_SECURITY_ID,
            instrument_symbol=" ",
        )


def test_accepts_tick_at_915() -> None:
    builder = make_builder()

    accepted = builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    assert accepted is True
    assert builder.tick_count == 1


def test_accepts_tick_at_915_59() -> None:
    builder = make_builder()

    accepted = builder.process_tick(
        tick(
            100.0,
            9,
            15,
            59,
        )
    )

    assert accepted is True
    assert builder.tick_count == 1


def test_ignores_tick_before_915() -> None:
    builder = make_builder()

    accepted = builder.process_tick(
        tick(
            100.0,
            9,
            14,
            59,
        )
    )

    assert accepted is False
    assert builder.tick_count == 0


def test_ignores_tick_at_916() -> None:
    builder = make_builder()

    accepted = builder.process_tick(
        tick(
            100.0,
            9,
            16,
            0,
        )
    )

    assert accepted is False
    assert builder.tick_count == 0


def test_ignores_tick_after_916() -> None:
    builder = make_builder()

    accepted = builder.process_tick(
        tick(
            100.0,
            9,
            17,
            0,
        )
    )

    assert accepted is False
    assert builder.tick_count == 0


def test_ignores_wrong_security_id() -> None:
    builder = make_builder()

    accepted = builder.process_tick(
        tick(
            price=100.0,
            hour=9,
            minute=15,
            second=30,
            security_id="999999",
        )
    )

    assert accepted is False
    assert builder.tick_count == 0


def test_builds_correct_one_minute_ohlc() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    builder.process_tick(
        tick(
            120.0,
            9,
            15,
            15,
        )
    )

    builder.process_tick(
        tick(
            80.0,
            9,
            15,
            30,
        )
    )

    builder.process_tick(
        tick(
            110.0,
            9,
            15,
            59,
        )
    )

    candle = builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    assert candle.open == 100.0
    assert candle.high == 120.0
    assert candle.low == 80.0
    assert candle.close == 110.0

    assert candle.start_time == datetime(
        2026,
        8,
        7,
        9,
        15,
    )

    assert candle.end_time == datetime(
        2026,
        8,
        7,
        9,
        16,
    )

    assert (
        candle.instrument_security_id
        == INSTRUMENT_SECURITY_ID
    )

    assert (
        candle.instrument_symbol
        == INSTRUMENT_SYMBOL
    )

    assert builder.tick_count == 4
    assert builder.is_finalized is True


def test_first_tick_becomes_open() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            101.25,
            9,
            15,
            2,
        )
    )

    builder.process_tick(
        tick(
            105.00,
            9,
            15,
            3,
        )
    )

    candle = builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    assert candle.open == 101.25


def test_last_accepted_tick_becomes_close() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    builder.process_tick(
        tick(
            108.25,
            9,
            15,
            59,
        )
    )

    candle = builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    assert candle.close == 108.25


def test_tick_at_916_cannot_change_close() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    builder.process_tick(
        tick(
            108.25,
            9,
            15,
            59,
        )
    )

    assert (
        builder.process_tick(
            tick(
                500.0,
                9,
                16,
                0,
            )
        )
        is False
    )

    candle = builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    assert candle.close == 108.25
    assert candle.high == 108.25


def test_rejects_out_of_order_tick() -> None:
    builder = make_builder()

    assert (
        builder.process_tick(
            tick(
                100.0,
                9,
                15,
                10,
            )
        )
        is True
    )

    assert (
        builder.process_tick(
            tick(
                90.0,
                9,
                15,
                5,
            )
        )
        is False
    )

    assert builder.tick_count == 1

    candle = builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    assert candle.low == 100.0


def test_rejects_tick_from_different_date() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            price=100.0,
            hour=9,
            minute=15,
            second=0,
            day=7,
        )
    )

    accepted = builder.process_tick(
        tick(
            price=120.0,
            hour=9,
            minute=15,
            second=30,
            day=8,
        )
    )

    assert accepted is False
    assert builder.tick_count == 1


def test_cannot_finalize_before_916() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    with pytest.raises(
        RuntimeError,
        match="cannot be finalized before window_end",
    ):
        builder.finalize(
            datetime(
                2026,
                8,
                7,
                9,
                15,
                59,
            )
        )


def test_can_finalize_exactly_at_916() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    candle = builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    assert candle.end_time == datetime(
        2026,
        8,
        7,
        9,
        16,
    )


def test_cannot_finalize_without_ticks() -> None:
    builder = make_builder()

    with pytest.raises(
        RuntimeError,
        match="has no market ticks",
    ):
        builder.finalize(
            datetime(
                2026,
                8,
                7,
                9,
                16,
            )
        )


def test_finalization_is_idempotent() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    first = builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    second = builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            20,
        )
    )

    assert first is second


def test_ticks_are_ignored_after_finalization() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    accepted = builder.process_tick(
        tick(
            150.0,
            9,
            15,
            30,
        )
    )

    assert accepted is False
    assert builder.tick_count == 1


def test_reset_clears_builder() -> None:
    builder = make_builder()

    builder.process_tick(
        tick(
            100.0,
            9,
            15,
            0,
        )
    )

    builder.finalize(
        datetime(
            2026,
            8,
            7,
            9,
            16,
        )
    )

    builder.reset()

    assert builder.tick_count == 0
    assert builder.trading_date is None
    assert builder.get_candle() is None
    assert builder.is_finalized is False

    assert (
        builder.security_id
        == INSTRUMENT_SECURITY_ID
    )

    assert (
        builder.instrument_symbol
        == INSTRUMENT_SYMBOL
    )

    assert builder.window_start == time(9, 15)
    assert builder.window_end == time(9, 16)