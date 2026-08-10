from datetime import date, datetime, time

import pytest

from src.strategy.strategy_types import (
    StrategySessionState,
)
from src.strategy.trading_session_manager import (
    TradingSessionConfig,
    TradingSessionManager,
)


TRADING_DATE = date(2026, 8, 7)


def dt(
    hour: int,
    minute: int,
    second: int = 0,
) -> datetime:
    return datetime(
        2026,
        8,
        7,
        hour,
        minute,
        second,
    )


def test_default_config() -> None:
    config = TradingSessionConfig()

    assert config.market_open == time(9, 15)

    assert (
        config.reference_candle_end
        == time(9, 16)
    )

    # Monitoring begins only after the complete 09:20
    # one-minute candle has closed.
    assert (
        config.monitoring_start
        == time(9, 21)
    )

    assert config.force_exit == time(15, 15)


def test_invalid_reference_candle_end_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "reference_candle_end must be "
            "after market_open"
        ),
    ):
        TradingSessionConfig(
            market_open=time(9, 15),
            reference_candle_end=time(9, 15),
            monitoring_start=time(9, 20),
            force_exit=time(15, 15),
        )


def test_monitoring_start_before_reference_end_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "monitoring_start cannot be before "
            "reference_candle_end"
        ),
    ):
        TradingSessionConfig(
            market_open=time(9, 15),
            reference_candle_end=time(9, 16),
            monitoring_start=time(9, 15),
            force_exit=time(15, 15),
        )


def test_force_exit_before_monitoring_start_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "force_exit must be after monitoring_start"
        ),
    ):
        TradingSessionConfig(
            market_open=time(9, 15),
            reference_candle_end=time(9, 16),
            monitoring_start=time(15, 15),
            force_exit=time(15, 15),
        )


def test_before_market_state() -> None:
    manager = TradingSessionManager()

    state = manager.update(
        dt(
            9,
            14,
            59,
        )
    )

    assert (
        state
        is StrategySessionState.WAITING_FOR_MARKET
    )


def test_reference_candle_state_at_915() -> None:
    manager = TradingSessionManager()

    state = manager.update(
        dt(
            9,
            15,
            0,
        )
    )

    assert (
        state
        is StrategySessionState.BUILDING_REFERENCE_CANDLE
    )


def test_reference_candle_state_before_916() -> None:
    manager = TradingSessionManager()

    state = manager.update(
        dt(
            9,
            15,
            59,
        )
    )

    assert (
        state
        is StrategySessionState.BUILDING_REFERENCE_CANDLE
    )


def test_916_reference_candle_is_complete() -> None:
    manager = TradingSessionManager()

    state = manager.update(
        dt(
            9,
            16,
            0,
        )
    )

    assert (
        state
        is StrategySessionState.LEVELS_READY
    )


def test_levels_ready_does_not_monitor_before_monitoring_start() -> None:
    manager = TradingSessionManager()

    assert (
        manager.update(
            dt(
                9,
                16,
                0,
            )
        )
        is StrategySessionState.LEVELS_READY
    )

    manager.mark_levels_ready()

    assert (
        manager.state()
        is StrategySessionState.LEVELS_READY
    )

    assert (
        manager.update(
            dt(
                9,
                19,
                59,
            )
        )
        is StrategySessionState.LEVELS_READY
    )


def test_mark_levels_ready_at_monitoring_start_enters_monitoring() -> None:
    manager = TradingSessionManager()

    manager.update(
        dt(
            9,
            21,
            0,
        )
    )

    manager.mark_levels_ready()

    assert (
        manager.state()
        is StrategySessionState.MONITORING
    )


def test_levels_ready_before_921_enters_monitoring_at_921() -> None:
    manager = TradingSessionManager()

    manager.update(
        dt(
            9,
            16,
            0,
        )
    )

    manager.mark_levels_ready()

    state = manager.update(
        dt(
            9,
            21,
            0,
        )
    )

    assert (
        state
        is StrategySessionState.MONITORING
    )


def test_after_levels_ready_remains_monitoring() -> None:
    manager = TradingSessionManager()

    manager.update(
        dt(
            9,
            16,
        )
    )

    manager.mark_levels_ready()

    manager.update(
        dt(
            9,
            21,
        )
    )

    state = manager.update(
        dt(
            10,
            30,
        )
    )

    assert (
        state
        is StrategySessionState.MONITORING
    )


def test_force_exit_at_1515() -> None:
    manager = TradingSessionManager()

    manager.update(
        dt(
            9,
            16,
        )
    )

    manager.mark_levels_ready()

    manager.update(
        dt(
            9,
            21,
        )
    )

    state = manager.update(
        dt(
            15,
            15,
        )
    )

    assert (
        state
        is StrategySessionState.CLOSED
    )


def test_after_force_exit_is_closed() -> None:
    manager = TradingSessionManager()

    state = manager.update(
        dt(
            15,
            30,
        )
    )

    assert (
        state
        is StrategySessionState.CLOSED
    )


def test_reference_candle_window() -> None:
    manager = TradingSessionManager()

    assert (
        manager.is_reference_candle_window(
            dt(
                9,
                15,
                0,
            )
        )
        is True
    )

    assert (
        manager.is_reference_candle_window(
            dt(
                9,
                15,
                59,
            )
        )
        is True
    )

    assert (
        manager.is_reference_candle_window(
            dt(
                9,
                16,
                0,
            )
        )
        is False
    )


def test_force_exit_check() -> None:
    manager = TradingSessionManager()

    assert (
        manager.is_force_exit_time(
            dt(
                15,
                14,
                59,
            )
        )
        is False
    )

    assert (
        manager.is_force_exit_time(
            dt(
                15,
                15,
                0,
            )
        )
        is True
    )


def test_can_monitor_levels_only_after_levels_ready() -> None:
    manager = TradingSessionManager()

    assert (
        manager.can_monitor_levels(
            dt(
                9,
                16,
                0,
            )
        )
        is False
    )

    manager.mark_levels_ready()

    assert (
        manager.can_monitor_levels(
            dt(
                9,
                20,
                59,
            )
        )
        is False
    )

    assert (
        manager.can_monitor_levels(
            dt(
                9,
                21,
                0,
            )
        )
        is True
    )


def test_new_day_resets_levels_ready() -> None:
    manager = TradingSessionManager()

    manager.update(
        dt(
            9,
            16,
        )
    )

    manager.mark_levels_ready()

    manager.update(
        dt(
            9,
            21,
        )
    )

    assert (
        manager.state()
        is StrategySessionState.MONITORING
    )

    next_day = datetime(
        2026,
        8,
        8,
        9,
        20,
    )

    state = manager.update(
        next_day
    )

    assert (
        manager.trading_date
        == date(
            2026,
            8,
            8,
        )
    )

    assert (
        state
        is StrategySessionState.LEVELS_READY
    )


def test_manual_reset_for_day() -> None:
    manager = TradingSessionManager()

    manager.reset_for_day(
        TRADING_DATE
    )

    assert (
        manager.trading_date
        == TRADING_DATE
    )

    assert (
        manager.state()
        is StrategySessionState.WAITING_FOR_MARKET
    )
