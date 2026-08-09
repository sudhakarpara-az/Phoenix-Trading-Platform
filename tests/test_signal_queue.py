from datetime import date, datetime
from threading import Thread
from time import sleep

import pytest

from src.signals.signal_queue import SignalQueue
from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)
from src.strategy.strategy_types import EntryLevel


TRADING_DATE = date(2026, 8, 7)


def make_signal(
    sequence: int,
    level: EntryLevel = EntryLevel.K5,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            f"SIG-20260807-{level.value}-{sequence:06d}"
        ),
        trading_date=TRADING_DATE,
        level=level,
        direction=SignalDirection.CALL,
        instrument_security_id="12345",
        instrument_symbol="NIFTY-24550-CE",
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=datetime(
            2026,
            8,
            7,
            10,
            0,
            sequence,
        ),
    )


def test_queue_starts_empty() -> None:
    queue = SignalQueue()

    assert queue.size() == 0
    assert queue.is_empty() is True
    assert queue.peek() is None


def test_put_signal() -> None:
    queue = SignalQueue()

    signal = make_signal(1)

    assert queue.put(signal) is True

    assert queue.size() == 1
    assert queue.is_empty() is False


def test_get_signal() -> None:
    queue = SignalQueue()

    signal = make_signal(1)

    queue.put(signal)

    result = queue.get()

    assert result is signal
    assert queue.size() == 0


def test_fifo_order() -> None:
    queue = SignalQueue()

    first = make_signal(
        1,
        EntryLevel.K5,
    )

    second = make_signal(
        2,
        EntryLevel.K6,
    )

    third = make_signal(
        3,
        EntryLevel.K7,
    )

    queue.put(first)
    queue.put(second)
    queue.put(third)

    assert queue.get() is first
    assert queue.get() is second
    assert queue.get() is third


def test_get_empty_queue_returns_none() -> None:
    queue = SignalQueue()

    assert queue.get() is None


def test_peek_does_not_remove_signal() -> None:
    queue = SignalQueue()

    signal = make_signal(1)

    queue.put(signal)

    assert queue.peek() is signal
    assert queue.size() == 1

    assert queue.get() is signal


def test_max_size_blocks_additional_signal() -> None:
    queue = SignalQueue(
        max_size=2
    )

    assert queue.put(
        make_signal(1)
    ) is True

    assert queue.put(
        make_signal(2)
    ) is True

    assert queue.put(
        make_signal(3)
    ) is False

    assert queue.size() == 2


def test_space_available_after_get() -> None:
    queue = SignalQueue(
        max_size=1
    )

    assert queue.put(
        make_signal(1)
    ) is True

    assert queue.put(
        make_signal(2)
    ) is False

    queue.get()

    assert queue.put(
        make_signal(2)
    ) is True


def test_clear_returns_removed_count() -> None:
    queue = SignalQueue()

    queue.put(
        make_signal(1)
    )

    queue.put(
        make_signal(2)
    )

    removed = queue.clear()

    assert removed == 2
    assert queue.is_empty() is True


def test_snapshot_preserves_fifo_order() -> None:
    queue = SignalQueue()

    first = make_signal(1)
    second = make_signal(2)

    queue.put(first)
    queue.put(second)

    snapshot = queue.snapshot()

    assert snapshot == (
        first,
        second,
    )

    assert queue.size() == 2


def test_invalid_max_size_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="max_size must be greater than zero",
    ):
        SignalQueue(
            max_size=0
        )


def test_negative_timeout_is_rejected() -> None:
    queue = SignalQueue()

    with pytest.raises(
        ValueError,
        match="timeout cannot be negative",
    ):
        queue.get(
            block=True,
            timeout=-1,
        )


def test_blocking_get_receives_signal() -> None:
    queue = SignalQueue()

    expected = make_signal(1)

    result_holder: list[
        TradingSignal | None
    ] = []

    def consumer() -> None:
        result = queue.get(
            block=True,
            timeout=1.0,
        )

        result_holder.append(
            result
        )

    thread = Thread(
        target=consumer
    )

    thread.start()

    sleep(0.05)

    queue.put(expected)

    thread.join(
        timeout=1.0
    )

    assert thread.is_alive() is False

    assert result_holder == [
        expected
    ]


def test_blocking_get_timeout_returns_none() -> None:
    queue = SignalQueue()

    result = queue.get(
        block=True,
        timeout=0.05,
    )

    assert result is None