from datetime import date, datetime, time

import pytest

from src.strategy.strategy_types import StrategySessionState
from src.strategy.trading_session_manager import (
    TradingSessionConfig,
    TradingSessionManager,
)


TRADING_DATE = date(2026, 8, 7)


def dt(hour: int, minute: int, second: int = 0) -> datetime:
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
    assert config.reference_candle_end == time(9, 20)
    assert config.force_exit == time(15, 15)


def test_invalid_reference_candle_end_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="reference_candle_end must be after market_open",
    ):
        TradingSessionConfig(
            market_open=time(9, 15),
            reference_candle_end=time(9, 15),
            force_exit=time(15, 15),
        )


def test_before_market_state() -> None:
    manager = TradingSessionManager()

    state = manager.update(dt(9, 14, 59))

    assert state is StrategySessionState.WAITING_FOR_MARKET


def test_reference_candle_state_at_915() -> None:
    manager = TradingSessionManager()

    state = manager.update(dt(9, 15))

    assert (
        state
        is StrategySessionState.BUILDING_REFERENCE_CANDLE
    )


def test_reference_candle_state_before_920() -> None:
    manager = TradingSessionManager()

    state = manager.update(dt(9, 19, 59))

    assert (
        state
        is StrategySessionState.BUILDING_REFERENCE_CANDLE
    )


def test_920_waits_for_levels() -> None:
    manager = TradingSessionManager()

    state = manager.update(dt(9, 20))

    assert state is StrategySessionState.LEVELS_READY


def test_mark_levels_ready_enters_monitoring() -> None:
    manager = TradingSessionManager()

    manager.update(dt(9, 20))

    manager.mark_levels_ready()

    assert manager.state() is StrategySessionState.MONITORING


def test_after_levels_ready_remains_monitoring() -> None:
    manager = TradingSessionManager()

    manager.update(dt(9, 20))
    manager.mark_levels_ready()

    state = manager.update(dt(10, 30))

    assert state is StrategySessionState.MONITORING


def test_force_exit_at_1515() -> None:
    manager = TradingSessionManager()

    manager.update(dt(9, 20))
    manager.mark_levels_ready()

    state = manager.update(dt(15, 15))

    assert state is StrategySessionState.CLOSED


def test_after_force_exit_is_closed() -> None:
    manager = TradingSessionManager()

    state = manager.update(dt(15, 30))

    assert state is StrategySessionState.CLOSED


def test_reference_candle_window() -> None:
    manager = TradingSessionManager()

    assert manager.is_reference_candle_window(dt(9, 15)) is True
    assert manager.is_reference_candle_window(dt(9, 19, 59)) is True
    assert manager.is_reference_candle_window(dt(9, 20)) is False


def test_force_exit_check() -> None:
    manager = TradingSessionManager()

    assert manager.is_force_exit_time(dt(15, 14, 59)) is False
    assert manager.is_force_exit_time(dt(15, 15)) is True


def test_can_monitor_levels_only_after_levels_ready() -> None:
    manager = TradingSessionManager()

    assert manager.can_monitor_levels(dt(9, 20)) is False

    manager.mark_levels_ready()

    assert manager.can_monitor_levels(dt(9, 21)) is True


def test_new_day_resets_levels_ready() -> None:
    manager = TradingSessionManager()

    manager.update(dt(9, 20))
    manager.mark_levels_ready()

    assert manager.state() is StrategySessionState.MONITORING

    next_day = datetime(
        2026,
        8,
        8,
        9,
        20,
    )

    state = manager.update(next_day)

    assert manager.trading_date == date(2026, 8, 8)
    assert state is StrategySessionState.LEVELS_READY


def test_manual_reset_for_day() -> None:
    manager = TradingSessionManager()

    manager.reset_for_day(TRADING_DATE)

    assert manager.trading_date == TRADING_DATE
    assert manager.state() is StrategySessionState.WAITING_FOR_MARKET