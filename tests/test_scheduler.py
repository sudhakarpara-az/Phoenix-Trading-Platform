"""
Tests for Phoenix M10 trading-day scheduler domain contracts.
"""

from datetime import date, datetime

import pytest

from src.services.scheduler import (
    TradingCalendar,
    TradingDayScheduler,
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


def test_trading_calendar_weekday_is_trading_day() -> None:
    calendar = TradingCalendar()

    assert calendar.is_trading_day(
        date(2026, 8, 10)
    ) is True


def test_trading_calendar_saturday_is_not_trading_day() -> None:
    calendar = TradingCalendar()

    trading_date = date(
        2026,
        8,
        8,
    )

    assert calendar.is_weekend(
        trading_date
    ) is True

    assert calendar.is_trading_day(
        trading_date
    ) is False


def test_trading_calendar_sunday_is_not_trading_day() -> None:
    calendar = TradingCalendar()

    trading_date = date(
        2026,
        8,
        9,
    )

    assert calendar.is_weekend(
        trading_date
    ) is True

    assert calendar.is_trading_day(
        trading_date
    ) is False


def test_explicit_weekday_holiday_is_not_trading_day() -> None:
    holiday = date(
        2026,
        8,
        11,
    )

    calendar = TradingCalendar(
        holidays=frozenset(
            {
                holiday,
            }
        )
    )

    assert calendar.is_holiday(
        holiday
    ) is True

    assert calendar.is_trading_day(
        holiday
    ) is False


def test_non_holiday_weekday_remains_trading_day() -> None:
    calendar = TradingCalendar(
        holidays=frozenset(
            {
                date(
                    2026,
                    8,
                    11,
                ),
            }
        )
    )

    assert calendar.is_trading_day(
        date(
            2026,
            8,
            12,
        )
    ) is True


def test_calendar_holidays_are_immutable() -> None:
    holiday = date(
        2026,
        8,
        11,
    )

    calendar = TradingCalendar(
        holidays=frozenset(
            {
                holiday,
            }
        )
    )

    assert isinstance(
        calendar.holidays,
        frozenset,
    )

    assert calendar.holidays == frozenset(
        {
            holiday,
        }
    )


def test_calendar_rejects_datetime_as_holiday() -> None:
    with pytest.raises(
        TypeError,
        match=(
            "trading calendar holidays must "
            "contain date values"
        ),
    ):
        TradingCalendar(
            holidays=frozenset(
                {
                    datetime(
                        2026,
                        8,
                        11,
                        0,
                        0,
                    ),
                }
            )
        )


def test_calendar_rejects_datetime_as_trading_date() -> None:
    calendar = TradingCalendar()

    with pytest.raises(
        TypeError,
        match="trading_date must be a date",
    ):
        calendar.is_trading_day(
            datetime(
                2026,
                8,
                10,
                9,
                15,
            )
        )


def test_scheduler_starts_eligible_trading_day() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    snapshot = scheduler.start(
        started_at=STARTED_AT,
    )

    assert snapshot.state is TradingDayState.WAITING_FOR_MARKET
    assert snapshot.started_at == STARTED_AT
    assert snapshot.updated_at == STARTED_AT
    assert snapshot.closed_at is None
    assert scheduler.state is TradingDayState.WAITING_FOR_MARKET


def test_scheduler_closes_weekend_on_start() -> None:
    saturday = date(
        2026,
        8,
        8,
    )

    scheduler = TradingDayScheduler(
        trading_date=saturday,
        created_at=datetime(
            2026,
            8,
            8,
            8,
            0,
        ),
    )

    started_at = datetime(
        2026,
        8,
        8,
        9,
        0,
    )

    snapshot = scheduler.start(
        started_at=started_at,
    )

    assert snapshot.state is TradingDayState.NON_TRADING_DAY
    assert snapshot.is_terminal is True
    assert snapshot.closed_at == started_at


def test_scheduler_closes_explicit_holiday_on_start() -> None:
    calendar = TradingCalendar(
        holidays=frozenset(
            {
                TRADING_DATE,
            }
        )
    )

    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
        calendar=calendar,
    )

    snapshot = scheduler.start(
        started_at=STARTED_AT,
    )

    assert snapshot.state is TradingDayState.NON_TRADING_DAY
    assert snapshot.is_terminal is True


def test_scheduler_normal_transition_sequence() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    transitions = (
        (
            TradingDayState.WAITING_FOR_REFERENCE_CLOSE,
            datetime(2026, 8, 10, 9, 15),
        ),
        (
            TradingDayState.SELECTING_OPTIONS,
            datetime(2026, 8, 10, 9, 16),
        ),
        (
            TradingDayState.PREPARING_LEVELS,
            datetime(2026, 8, 10, 9, 16, 1),
        ),
        (
            TradingDayState.WAITING_FOR_MONITORING,
            datetime(2026, 8, 10, 9, 17),
        ),
        (
            TradingDayState.MONITORING,
            datetime(2026, 8, 10, 9, 21),
        ),
        (
            TradingDayState.EXIT_ONLY,
            datetime(2026, 8, 10, 15, 15),
        ),
        (
            TradingDayState.CLOSED,
            datetime(2026, 8, 10, 15, 16),
        ),
    )

    for target_state, transitioned_at in transitions:
        snapshot = scheduler.transition(
            target_state=target_state,
            transitioned_at=transitioned_at,
        )

        assert snapshot.state is target_state

    assert scheduler.snapshot.is_terminal is True
    assert scheduler.snapshot.closed_at == datetime(
        2026,
        8,
        10,
        15,
        16,
    )


def test_scheduler_rejects_skipped_morning_transition() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    with pytest.raises(
        TradingDayTransitionError,
        match=(
            "WAITING_FOR_MARKET -> "
            "SELECTING_OPTIONS"
        ),
    ):
        scheduler.transition(
            target_state=TradingDayState.SELECTING_OPTIONS,
            transitioned_at=datetime(
                2026,
                8,
                10,
                9,
                16,
            ),
        )


@pytest.mark.parametrize(
    "state",
    [
        TradingDayState.WAITING_FOR_MARKET,
        TradingDayState.WAITING_FOR_REFERENCE_CLOSE,
        TradingDayState.SELECTING_OPTIONS,
        TradingDayState.PREPARING_LEVELS,
        TradingDayState.WAITING_FOR_MONITORING,
        TradingDayState.MONITORING,
    ],
)
def test_active_state_can_enter_exit_only(
    state: TradingDayState,
) -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    path = [
        TradingDayState.WAITING_FOR_REFERENCE_CLOSE,
        TradingDayState.SELECTING_OPTIONS,
        TradingDayState.PREPARING_LEVELS,
        TradingDayState.WAITING_FOR_MONITORING,
        TradingDayState.MONITORING,
    ]

    current_at = datetime(
        2026,
        8,
        10,
        9,
        15,
    )

    for target in path:
        if scheduler.state is state:
            break

        scheduler.transition(
            target_state=target,
            transitioned_at=current_at,
        )

        current_at = current_at.replace(
            minute=current_at.minute + 1
        )

    assert scheduler.state is state

    snapshot = scheduler.transition(
        target_state=TradingDayState.EXIT_ONLY,
        transitioned_at=FORCE_EXIT_AT,
    )

    assert snapshot.state is TradingDayState.EXIT_ONLY
    assert snapshot.can_accept_new_entries is False
    assert snapshot.can_manage_positions is True


def test_scheduler_cannot_transition_from_terminal_day() -> None:
    calendar = TradingCalendar(
        holidays=frozenset(
            {
                TRADING_DATE,
            }
        )
    )

    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
        calendar=calendar,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    assert scheduler.can_transition_to(
        TradingDayState.WAITING_FOR_MARKET
    ) is False

    with pytest.raises(
        TradingDayTransitionError,
        match="illegal trading-day transition",
    ):
        scheduler.transition(
            target_state=TradingDayState.WAITING_FOR_MARKET,
            transitioned_at=STARTED_AT,
        )


def test_scheduler_rejects_backward_transition_time() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    with pytest.raises(
        TradingDayTransitionError,
        match=(
            "transition timestamp cannot move backwards"
        ),
    ):
        scheduler.transition(
            target_state=(
                TradingDayState.WAITING_FOR_REFERENCE_CLOSE
            ),
            transitioned_at=CREATED_AT,
        )


def test_scheduler_can_fail_active_day() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    snapshot = scheduler.fail(
        message=" scheduler coordination failed ",
        failed_at=datetime(
            2026,
            8,
            10,
            9,
            10,
        ),
    )

    assert snapshot.state is TradingDayState.FAILED
    assert snapshot.failure_message == (
        "scheduler coordination failed"
    )
    assert snapshot.is_terminal is True


def test_scheduler_terminal_day_cannot_fail() -> None:
    calendar = TradingCalendar(
        holidays=frozenset(
            {
                TRADING_DATE,
            }
        )
    )

    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
        calendar=calendar,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    with pytest.raises(
        TradingDayTransitionError,
        match="terminal trading day cannot fail",
    ):
        scheduler.fail(
            message="unexpected",
            failed_at=STARTED_AT,
        )


def test_scheduler_start_is_not_repeatable() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    with pytest.raises(
        TradingDayTransitionError,
        match="can only start from CREATED",
    ):
        scheduler.start(
            started_at=STARTED_AT,
        )


def test_scheduler_rejects_empty_failure_message() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=CREATED_AT,
    )

    scheduler.start(
        started_at=STARTED_AT,
    )

    with pytest.raises(
        ValueError,
        match="failure message cannot be empty",
    ):
        scheduler.fail(
            message="   ",
            failed_at=STARTED_AT,
        )
