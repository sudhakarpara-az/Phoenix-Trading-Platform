from datetime import datetime

import pytest

from src.market.market_types import (
    Exchange,
    MarketTick,
)
from src.strategy.reference_candle_builder import (
    ReferenceCandleBuilder,
)


def tick(
    price: float,
    hour: int,
    minute: int,
    second: int = 0,
    security_id: str = "13",
    day: int = 7,
) -> MarketTick:
    return MarketTick(
        exchange=Exchange.IDX,
        symbol="NIFTY 50",
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


def test_accepts_tick_at_915() -> None:
    builder = ReferenceCandleBuilder()

    accepted = builder.process_tick(
        tick(24500.0, 9, 15)
    )

    assert accepted is True
    assert builder.tick_count == 1


def test_ignores_tick_before_915() -> None:
    builder = ReferenceCandleBuilder()

    accepted = builder.process_tick(
        tick(24500.0, 9, 14, 59)
    )

    assert accepted is False
    assert builder.tick_count == 0


def test_ignores_tick_at_920() -> None:
    builder = ReferenceCandleBuilder()

    accepted = builder.process_tick(
        tick(24500.0, 9, 20)
    )

    assert accepted is False
    assert builder.tick_count == 0


def test_ignores_wrong_security_id() -> None:
    builder = ReferenceCandleBuilder()

    accepted = builder.process_tick(
        tick(
            price=100.0,
            hour=9,
            minute=16,
            security_id="999999",
        )
    )

    assert accepted is False
    assert builder.tick_count == 0


def test_builds_correct_ohlc() -> None:
    builder = ReferenceCandleBuilder()

    builder.process_tick(
        tick(24500.0, 9, 15, 0)
    )

    builder.process_tick(
        tick(24520.0, 9, 16, 0)
    )

    builder.process_tick(
        tick(24480.0, 9, 17, 0)
    )

    builder.process_tick(
        tick(24510.0, 9, 19, 59)
    )

    candle = builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    assert candle.open == 24500.0
    assert candle.high == 24520.0
    assert candle.low == 24480.0
    assert candle.close == 24510.0

    assert builder.tick_count == 4
    assert builder.is_finalized is True


def test_first_tick_becomes_open() -> None:
    builder = ReferenceCandleBuilder()

    builder.process_tick(
        tick(24501.25, 9, 15, 2)
    )

    builder.process_tick(
        tick(24505.00, 9, 15, 3)
    )

    candle = builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    assert candle.open == 24501.25


def test_last_tick_becomes_close() -> None:
    builder = ReferenceCandleBuilder()

    builder.process_tick(
        tick(24500.0, 9, 15)
    )

    builder.process_tick(
        tick(24508.25, 9, 19, 59)
    )

    candle = builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    assert candle.close == 24508.25


def test_rejects_out_of_order_tick() -> None:
    builder = ReferenceCandleBuilder()

    assert (
        builder.process_tick(
            tick(24500.0, 9, 16, 10)
        )
        is True
    )

    assert (
        builder.process_tick(
            tick(24400.0, 9, 16, 5)
        )
        is False
    )

    assert builder.tick_count == 1

    candle = builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    assert candle.low == 24500.0


def test_rejects_tick_from_different_date() -> None:
    builder = ReferenceCandleBuilder()

    builder.process_tick(
        tick(
            price=24500.0,
            hour=9,
            minute=15,
            day=7,
        )
    )

    accepted = builder.process_tick(
        tick(
            price=25000.0,
            hour=9,
            minute=16,
            day=8,
        )
    )

    assert accepted is False
    assert builder.tick_count == 1


def test_cannot_finalize_before_920() -> None:
    builder = ReferenceCandleBuilder()

    builder.process_tick(
        tick(24500.0, 9, 15)
    )

    with pytest.raises(
        RuntimeError,
        match="cannot be finalized before window_end",
    ):
        builder.finalize(
            datetime(2026, 8, 7, 9, 19, 59)
        )


def test_cannot_finalize_without_ticks() -> None:
    builder = ReferenceCandleBuilder()

    with pytest.raises(
        RuntimeError,
        match="has no market ticks",
    ):
        builder.finalize(
            datetime(2026, 8, 7, 9, 20)
        )


def test_finalization_is_idempotent() -> None:
    builder = ReferenceCandleBuilder()

    builder.process_tick(
        tick(24500.0, 9, 15)
    )

    first = builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    second = builder.finalize(
        datetime(2026, 8, 7, 9, 21)
    )

    assert first is second


def test_ticks_are_ignored_after_finalization() -> None:
    builder = ReferenceCandleBuilder()

    builder.process_tick(
        tick(24500.0, 9, 15)
    )

    builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    accepted = builder.process_tick(
        tick(25000.0, 9, 19)
    )

    assert accepted is False
    assert builder.tick_count == 1


def test_reset_clears_builder() -> None:
    builder = ReferenceCandleBuilder()

    builder.process_tick(
        tick(24500.0, 9, 15)
    )

    builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    builder.reset()

    assert builder.tick_count == 0
    assert builder.trading_date is None
    assert builder.get_candle() is None
    assert builder.is_finalized is False