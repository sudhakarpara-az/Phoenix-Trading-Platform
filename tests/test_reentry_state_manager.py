from datetime import date, datetime

import pytest

from src.signals.reentry_state_manager import (
    ReentryStateManager,
    ReentryStatus,
)
from src.strategy.strategy_types import EntryLevel


TRADING_DATE = date(2026, 8, 7)


def opened_at(
    hour: int = 10,
    minute: int = 0,
) -> datetime:
    return datetime(
        2026,
        8,
        7,
        hour,
        minute,
    )


def test_new_level_can_enter() -> None:
    manager = ReentryStateManager()

    assert manager.can_enter(EntryLevel.K5) is True
    assert manager.is_reentry(EntryLevel.K5) is False


def test_first_trade_is_not_reentry() -> None:
    manager = ReentryStateManager()

    assert manager.is_reentry(EntryLevel.K5) is False

    state = manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    assert state.status is ReentryStatus.ACTIVE
    assert state.trade_count == 1
    assert manager.is_reentry(EntryLevel.K5) is False


def test_active_level_cannot_enter_again() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    assert manager.can_enter(EntryLevel.K5) is False


def test_duplicate_open_is_rejected() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    with pytest.raises(
        RuntimeError,
        match="K5 already has an active trade",
    ):
        manager.mark_open(
            EntryLevel.K5,
            TRADING_DATE,
            opened_at(10, 5),
        )


def test_close_active_trade() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    closed = manager.mark_closed(
        EntryLevel.K5,
        opened_at(10, 30),
    )

    assert closed.status is ReentryStatus.CLOSED
    assert closed.trade_count == 1


def test_closed_level_becomes_reentry_eligible() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    manager.mark_closed(
        EntryLevel.K5,
        opened_at(10, 30),
    )

    assert manager.can_enter(EntryLevel.K5) is True
    assert manager.is_reentry(EntryLevel.K5) is True


def test_reentry_increments_trade_count() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    manager.mark_closed(
        EntryLevel.K5,
        opened_at(10, 30),
    )

    second = manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(11, 0),
    )

    assert second.status is ReentryStatus.ACTIVE
    assert second.trade_count == 2


def test_multiple_reentries_are_supported() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K7,
        TRADING_DATE,
        opened_at(10, 0),
    )

    manager.mark_closed(
        EntryLevel.K7,
        opened_at(10, 20),
    )

    manager.mark_open(
        EntryLevel.K7,
        TRADING_DATE,
        opened_at(11, 0),
    )

    manager.mark_closed(
        EntryLevel.K7,
        opened_at(11, 30),
    )

    third = manager.mark_open(
        EntryLevel.K7,
        TRADING_DATE,
        opened_at(12, 0),
    )

    assert third.trade_count == 3
    assert third.status is ReentryStatus.ACTIVE


def test_levels_are_tracked_independently() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    assert manager.can_enter(EntryLevel.K5) is False
    assert manager.can_enter(EntryLevel.K6) is True
    assert manager.can_enter(EntryLevel.K7) is True


def test_close_without_trade_history_is_rejected() -> None:
    manager = ReentryStateManager()

    with pytest.raises(
        RuntimeError,
        match="K6 has no trade history",
    ):
        manager.mark_closed(
            EntryLevel.K6,
            opened_at(),
        )


def test_close_already_closed_trade_is_rejected() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    manager.mark_closed(
        EntryLevel.K5,
        opened_at(10, 30),
    )

    with pytest.raises(
        RuntimeError,
        match="K5 does not have an active trade",
    ):
        manager.mark_closed(
            EntryLevel.K5,
            opened_at(10, 40),
        )


def test_trade_count_defaults_to_zero() -> None:
    manager = ReentryStateManager()

    assert manager.trade_count(EntryLevel.K5) == 0


def test_trade_count_after_first_trade() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K6,
        TRADING_DATE,
        opened_at(),
    )

    assert manager.trade_count(EntryLevel.K6) == 1


def test_trading_date_is_set_on_first_trade() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    assert manager.trading_date == TRADING_DATE


def test_new_day_with_active_trade_is_rejected() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    with pytest.raises(
        RuntimeError,
        match="cannot change trading date while trades are active",
    ):
        manager.mark_open(
            EntryLevel.K6,
            date(2026, 8, 8),
            datetime(
                2026,
                8,
                8,
                10,
                0,
            ),
        )


def test_new_day_resets_closed_history() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    manager.mark_closed(
        EntryLevel.K5,
        opened_at(10, 30),
    )

    manager.mark_open(
        EntryLevel.K6,
        date(2026, 8, 8),
        datetime(
            2026,
            8,
            8,
            10,
            0,
        ),
    )

    assert manager.trading_date == date(2026, 8, 8)

    assert manager.get_state(
        EntryLevel.K5
    ) is None

    assert manager.trade_count(
        EntryLevel.K5
    ) == 0


def test_reset_clears_all_state() -> None:
    manager = ReentryStateManager()

    manager.mark_open(
        EntryLevel.K5,
        TRADING_DATE,
        opened_at(),
    )

    manager.reset()

    assert manager.trading_date is None
    assert manager.get_state(EntryLevel.K5) is None
    assert manager.trade_count(EntryLevel.K5) == 0