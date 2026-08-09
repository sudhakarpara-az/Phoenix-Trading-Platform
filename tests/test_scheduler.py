"""
Tests for Phoenix M10 trading-day scheduler domain contracts.
"""

from datetime import date, datetime

import pytest

from src.services.scheduler import (
    TradingDaySnapshot,
    TradingDayState,
    TradingDayTransitionError,
)


TRADING_DATE = date(2026, 8, 10)

CREATED_AT = datetime(
    2026,
    8,
    10,
    8,
    0,
)

STARTED_AT = datetime(
    2026,
    8,
    10,
    9,
    0,
)

MONITORING_AT = datetime(
    2026,
    8,
    10,
    9,
    21,
)

FORCE_EXIT_AT = datetime(
    2026,
    8,
    10,
    15,
    15,
)

CLOSED_AT = datetime(
    2026,
    8,
    10,
    15,
    20,
)


def test_trading_day_states_are_stable() -> None:
    assert {
        state.value
        for state in TradingDayState
    } == {
        "CREATED",
        "NON_TRADING_DAY",
        "WAITING_FOR_MARKET",
        "WAITING_FOR_REFERENCE_CLOSE",
        "SELECTING_OPTIONS",
        "PREPARING_LEVELS",
        "WAITING_FOR_MONITORING",
        "MONITORING",
        "EXIT_ONLY",
        "CLOSED",
        "FAILED",
    }


def test_created_snapshot() -> None:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.CREATED,
        updated_at=CREATED_AT,
    )

    assert snapshot.trading_date == TRADING_DATE
    assert snapshot.state is TradingDayState.CREATED
    assert snapshot.started_at is None
    assert snapshot.closed_at is None
    assert snapshot.failure_message is None
    assert snapshot.is_terminal is False
    assert snapshot.can_accept_new_entries is False
    assert snapshot.can_manage_positions is False


def test_waiting_for_market_snapshot() -> None:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.WAITING_FOR_MARKET,
        started_at=STARTED_AT,
        updated_at=STARTED_AT,
    )

    assert snapshot.is_terminal is False
    assert snapshot.can_accept_new_entries is False
    assert snapshot.can_manage_positions is False


@pytest.mark.parametrize(
    "state",
    [
        TradingDayState.WAITING_FOR_REFERENCE_CLOSE,
        TradingDayState.SELECTING_OPTIONS,
        TradingDayState.PREPARING_LEVELS,
        TradingDayState.WAITING_FOR_MONITORING,
    ],
)
def test_preparation_states_block_entries(
    state: TradingDayState,
) -> None:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=state,
        started_at=STARTED_AT,
        updated_at=MONITORING_AT,
    )

    assert snapshot.can_accept_new_entries is False
    assert snapshot.can_manage_positions is False


def test_monitoring_allows_entries_and_position_management() -> None:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.MONITORING,
        started_at=STARTED_AT,
        updated_at=MONITORING_AT,
    )

    assert snapshot.can_accept_new_entries is True
    assert snapshot.can_manage_positions is True


def test_exit_only_blocks_entries_but_manages_positions() -> None:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.EXIT_ONLY,
        started_at=STARTED_AT,
        updated_at=FORCE_EXIT_AT,
    )

    assert snapshot.can_accept_new_entries is False
    assert snapshot.can_manage_positions is True
    assert snapshot.is_terminal is False


def test_closed_is_terminal() -> None:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.CLOSED,
        started_at=STARTED_AT,
        closed_at=CLOSED_AT,
        updated_at=CLOSED_AT,
    )

    assert snapshot.is_terminal is True
    assert snapshot.can_accept_new_entries is False
    assert snapshot.can_manage_positions is False


def test_non_trading_day_is_terminal() -> None:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.NON_TRADING_DAY,
        started_at=STARTED_AT,
        closed_at=STARTED_AT,
        updated_at=STARTED_AT,
    )

    assert snapshot.is_terminal is True
    assert snapshot.can_accept_new_entries is False
    assert snapshot.can_manage_positions is False


def test_failed_requires_failure_message() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "FAILED trading day requires "
            "failure_message"
        ),
    ):
        TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=TradingDayState.FAILED,
            started_at=STARTED_AT,
            updated_at=STARTED_AT,
        )


def test_failed_snapshot_is_terminal() -> None:
    snapshot = TradingDaySnapshot(
        trading_date=TRADING_DATE,
        state=TradingDayState.FAILED,
        started_at=STARTED_AT,
        updated_at=STARTED_AT,
        failure_message=" scheduler failed ",
    )

    assert snapshot.failure_message == "scheduler failed"
    assert snapshot.is_terminal is True
    assert snapshot.can_accept_new_entries is False
    assert snapshot.can_manage_positions is False


def test_non_failed_state_rejects_failure_message() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "failure_message is only valid for "
            "FAILED state"
        ),
    ):
        TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=TradingDayState.MONITORING,
            started_at=STARTED_AT,
            updated_at=MONITORING_AT,
            failure_message="unexpected",
        )


def test_created_rejects_started_at() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "CREATED trading day cannot have started_at"
        ),
    ):
        TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=TradingDayState.CREATED,
            started_at=STARTED_AT,
            updated_at=STARTED_AT,
        )


def test_updated_at_cannot_precede_started_at() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "updated_at cannot be before started_at"
        ),
    ):
        TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=TradingDayState.WAITING_FOR_MARKET,
            started_at=STARTED_AT,
            updated_at=CREATED_AT,
        )


def test_terminal_state_requires_closed_at() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "CLOSED trading day requires closed_at"
        ),
    ):
        TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=TradingDayState.CLOSED,
            started_at=STARTED_AT,
            updated_at=CLOSED_AT,
        )


def test_non_terminal_state_rejects_closed_at() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "only terminal trading-day states "
            "may have closed_at"
        ),
    ):
        TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=TradingDayState.MONITORING,
            started_at=STARTED_AT,
            closed_at=CLOSED_AT,
            updated_at=CLOSED_AT,
        )


def test_transition_error_is_runtime_error() -> None:
    assert issubclass(
        TradingDayTransitionError,
        RuntimeError,
    )
