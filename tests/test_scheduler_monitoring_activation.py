"""
Tests for Phoenix M10 completed-09:20-candle monitoring
activation.
"""

from datetime import date, datetime, time

import pytest

from src.services.scheduler import (
    MonitoringWindowSchedule,
    TradingDayMonitoringCoordinator,
    TradingDayMonitoringError,
    TradingDayScheduler,
    TradingDayState,
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


def dt(
    hour: int,
    minute: int,
    second: int = 0,
) -> datetime:
    return datetime(
        2026,
        8,
        10,
        hour,
        minute,
        second,
    )


def make_waiting_scheduler() -> TradingDayScheduler:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=dt(
            9,
            0,
        )
    )

    scheduler.transition(
        target_state=(
            TradingDayState.WAITING_FOR_REFERENCE_CLOSE
        ),
        transitioned_at=dt(
            9,
            15,
        ),
    )

    scheduler.transition(
        target_state=(
            TradingDayState.SELECTING_OPTIONS
        ),
        transitioned_at=dt(
            9,
            16,
        ),
    )

    scheduler.transition(
        target_state=(
            TradingDayState.PREPARING_LEVELS
        ),
        transitioned_at=dt(
            9,
            16,
            1,
        ),
    )

    scheduler.transition(
        target_state=(
            TradingDayState.WAITING_FOR_MONITORING
        ),
        transitioned_at=dt(
            9,
            17,
        ),
    )

    return scheduler


def test_default_monitoring_schedule() -> None:
    schedule = MonitoringWindowSchedule()

    assert (
        schedule.monitoring_candle_start
        == time(
            9,
            20,
        )
    )

    assert (
        schedule.monitoring_start
        == time(
            9,
            21,
        )
    )


def test_monitoring_schedule_requires_exact_one_minute() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "monitoring_start must be exactly one minute "
            "after monitoring_candle_start"
        ),
    ):
        MonitoringWindowSchedule(
            monitoring_candle_start=time(
                9,
                20,
            ),
            monitoring_start=time(
                9,
                22,
            ),
        )


def test_monitoring_candle_not_open_before_920() -> None:
    coordinator = TradingDayMonitoringCoordinator(
        scheduler=make_waiting_scheduler()
    )

    assert (
        coordinator.is_monitoring_candle_open(
            dt(
                9,
                19,
                59,
            )
        )
        is False
    )


def test_monitoring_candle_opens_exactly_at_920() -> None:
    coordinator = TradingDayMonitoringCoordinator(
        scheduler=make_waiting_scheduler()
    )

    assert (
        coordinator.is_monitoring_candle_open(
            dt(
                9,
                20,
            )
        )
        is True
    )

    assert (
        coordinator.is_monitoring_ready(
            dt(
                9,
                20,
            )
        )
        is False
    )


def test_monitoring_candle_remains_open_until_921() -> None:
    coordinator = TradingDayMonitoringCoordinator(
        scheduler=make_waiting_scheduler()
    )

    assert (
        coordinator.is_monitoring_candle_open(
            dt(
                9,
                20,
                59,
            )
        )
        is True
    )

    assert (
        coordinator.is_monitoring_ready(
            dt(
                9,
                20,
                59,
            )
        )
        is False
    )


def test_monitoring_ready_exactly_at_921() -> None:
    coordinator = TradingDayMonitoringCoordinator(
        scheduler=make_waiting_scheduler()
    )

    assert (
        coordinator.is_monitoring_candle_open(
            dt(
                9,
                21,
            )
        )
        is False
    )

    assert (
        coordinator.is_monitoring_ready(
            dt(
                9,
                21,
            )
        )
        is True
    )


def test_activation_before_921_is_rejected() -> None:
    scheduler = make_waiting_scheduler()

    coordinator = TradingDayMonitoringCoordinator(
        scheduler=scheduler
    )

    with pytest.raises(
        TradingDayMonitoringError,
        match=(
            "monitoring cannot begin before the 09:20 "
            "one-minute candle has completed"
        ),
    ):
        coordinator.activate_monitoring(
            activated_at=dt(
                9,
                20,
                59,
            )
        )

    assert (
        scheduler.state
        is TradingDayState.WAITING_FOR_MONITORING
    )

    assert (
        scheduler.snapshot.can_accept_new_entries
        is False
    )


def test_activation_at_921_enters_monitoring() -> None:
    scheduler = make_waiting_scheduler()

    coordinator = TradingDayMonitoringCoordinator(
        scheduler=scheduler
    )

    snapshot = coordinator.activate_monitoring(
        activated_at=dt(
            9,
            21,
        )
    )

    assert (
        snapshot.state
        is TradingDayState.MONITORING
    )

    assert snapshot.can_accept_new_entries is True
    assert snapshot.can_manage_positions is True


def test_monitoring_activation_is_idempotent() -> None:
    scheduler = make_waiting_scheduler()

    coordinator = TradingDayMonitoringCoordinator(
        scheduler=scheduler
    )

    first = coordinator.activate_monitoring(
        activated_at=dt(
            9,
            21,
        )
    )

    second = coordinator.activate_monitoring(
        activated_at=dt(
            9,
            22,
        )
    )

    assert second is first

    assert (
        scheduler.state
        is TradingDayState.MONITORING
    )


def test_monitoring_activation_requires_waiting_state() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=dt(
            9,
            0,
        )
    )

    coordinator = TradingDayMonitoringCoordinator(
        scheduler=scheduler
    )

    with pytest.raises(
        TradingDayMonitoringError,
        match=(
            "monitoring activation requires "
            "WAITING_FOR_MONITORING state"
        ),
    ):
        coordinator.activate_monitoring(
            activated_at=dt(
                9,
                21,
            )
        )


def test_monitoring_activation_rejects_wrong_date() -> None:
    coordinator = TradingDayMonitoringCoordinator(
        scheduler=make_waiting_scheduler()
    )

    with pytest.raises(
        TradingDayMonitoringError,
        match=(
            "monitoring timestamp does not match "
            "scheduler trading_date"
        ),
    ):
        coordinator.activate_monitoring(
            activated_at=datetime(
                2026,
                8,
                11,
                9,
                21,
            )
        )
