"""
Tests for Phoenix M10 09:15 reference-window coordination.
"""

from datetime import date, datetime, time

import pytest

from src.services.scheduler import (
    ReferenceWindowSchedule,
    TradingDayReferenceCoordinator,
    TradingDayScheduler,
    TradingDayState,
    TradingDayTransitionError,
)


TRADING_DATE = date(
    2026,
    8,
    10,
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


def make_scheduler() -> TradingDayScheduler:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    return scheduler


def test_default_reference_schedule() -> None:
    schedule = ReferenceWindowSchedule()

    assert schedule.market_open == time(
        9,
        15,
    )

    assert schedule.reference_candle_end == time(
        9,
        16,
    )


def test_reference_schedule_rejects_invalid_window() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "reference_candle_end must be after "
            "market_open"
        ),
    ):
        ReferenceWindowSchedule(
            market_open=time(
                9,
                15,
            ),
            reference_candle_end=time(
                9,
                15,
            ),
        )


def test_reference_window_is_closed_before_915() -> None:
    coordinator = TradingDayReferenceCoordinator(
        scheduler=make_scheduler()
    )

    assert coordinator.is_reference_window_open(
        datetime(
            2026,
            8,
            10,
            9,
            14,
            59,
        )
    ) is False


def test_reference_window_opens_exactly_at_915() -> None:
    coordinator = TradingDayReferenceCoordinator(
        scheduler=make_scheduler()
    )

    assert coordinator.is_reference_window_open(
        datetime(
            2026,
            8,
            10,
            9,
            15,
        )
    ) is True


def test_reference_window_remains_open_before_916() -> None:
    coordinator = TradingDayReferenceCoordinator(
        scheduler=make_scheduler()
    )

    assert coordinator.is_reference_window_open(
        datetime(
            2026,
            8,
            10,
            9,
            15,
            59,
            999999,
        )
    ) is True


def test_reference_window_is_complete_exactly_at_916() -> None:
    coordinator = TradingDayReferenceCoordinator(
        scheduler=make_scheduler()
    )

    now = datetime(
        2026,
        8,
        10,
        9,
        16,
    )

    assert coordinator.is_reference_window_open(
        now
    ) is False

    assert coordinator.is_reference_window_complete(
        now
    ) is True


def test_reference_window_not_complete_before_916() -> None:
    coordinator = TradingDayReferenceCoordinator(
        scheduler=make_scheduler()
    )

    assert coordinator.is_reference_window_complete(
        datetime(
            2026,
            8,
            10,
            9,
            15,
            59,
        )
    ) is False


def test_begin_reference_window_at_915() -> None:
    scheduler = make_scheduler()

    coordinator = TradingDayReferenceCoordinator(
        scheduler=scheduler
    )

    snapshot = coordinator.begin_reference_window(
        opened_at=datetime(
            2026,
            8,
            10,
            9,
            15,
        )
    )

    assert (
        snapshot.state
        is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
    )

    assert (
        scheduler.state
        is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
    )


def test_begin_reference_window_is_idempotent() -> None:
    scheduler = make_scheduler()

    coordinator = TradingDayReferenceCoordinator(
        scheduler=scheduler
    )

    opened_at = datetime(
        2026,
        8,
        10,
        9,
        15,
    )

    first = coordinator.begin_reference_window(
        opened_at=opened_at
    )

    second = coordinator.begin_reference_window(
        opened_at=datetime(
            2026,
            8,
            10,
            9,
            15,
            30,
        )
    )

    assert second is first
    assert (
        scheduler.state
        is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
    )


def test_reference_window_cannot_begin_before_market_open() -> None:
    coordinator = TradingDayReferenceCoordinator(
        scheduler=make_scheduler()
    )

    with pytest.raises(
        TradingDayTransitionError,
        match=(
            "reference window cannot begin before "
            "market_open"
        ),
    ):
        coordinator.begin_reference_window(
            opened_at=datetime(
                2026,
                8,
                10,
                9,
                14,
                59,
            )
        )


def test_late_start_can_establish_reference_milestone() -> None:
    scheduler = make_scheduler()

    coordinator = TradingDayReferenceCoordinator(
        scheduler=scheduler
    )

    snapshot = coordinator.begin_reference_window(
        opened_at=datetime(
            2026,
            8,
            10,
            9,
            16,
            5,
        )
    )

    assert (
        snapshot.state
        is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
    )

    assert coordinator.is_reference_window_complete(
        datetime(
            2026,
            8,
            10,
            9,
            16,
            5,
        )
    ) is True


def test_reference_coordinator_rejects_wrong_date() -> None:
    coordinator = TradingDayReferenceCoordinator(
        scheduler=make_scheduler()
    )

    with pytest.raises(
        TradingDayTransitionError,
        match=(
            "timestamp does not match scheduler "
            "trading_date"
        ),
    ):
        coordinator.is_reference_window_complete(
            datetime(
                2026,
                8,
                11,
                9,
                16,
            )
        )


def test_reference_window_does_not_select_options() -> None:
    scheduler = make_scheduler()

    coordinator = TradingDayReferenceCoordinator(
        scheduler=scheduler
    )

    coordinator.begin_reference_window(
        opened_at=datetime(
            2026,
            8,
            10,
            9,
            15,
        )
    )

    assert coordinator.is_reference_window_complete(
        datetime(
            2026,
            8,
            10,
            9,
            16,
        )
    ) is True

    assert (
        scheduler.state
        is TradingDayState.WAITING_FOR_REFERENCE_CLOSE
    )
