"""
M10-T11 15:15 EXIT_ONLY and M07 force-exit coordination.
"""

from datetime import date, datetime, time

import pytest

from src.risk.force_exit_coordinator import (
    ForceExitBatch,
)
from src.services.scheduler import (
    ForceExitWindowSchedule,
    TradingDayForceExitCoordinator,
    TradingDayForceExitError,
    TradingDayScheduler,
    TradingDayState,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)


def dt(
    hour: int,
    minute: int,
    second: int = 0,
    *,
    day: int = 10,
) -> datetime:
    return datetime(
        2026,
        8,
        day,
        hour,
        minute,
        second,
    )


class FakeForceExitCoordinator:
    def __init__(
        self,
        *,
        scheduler: TradingDayScheduler | None = None,
        force_exit_time: time = time(
            15,
            15,
        ),
    ) -> None:
        self._force_exit_time = (
            force_exit_time
        )

        self.scheduler = scheduler

        self.calls: list[
            datetime
        ] = []

        self.state_seen_during_call: (
            TradingDayState
            | None
        ) = None

        self.batch_force_exit_reached = True

    @property
    def force_exit_time(
        self,
    ) -> time:
        return self._force_exit_time

    def evaluate_all(
        self,
        *,
        evaluated_at: datetime,
    ) -> ForceExitBatch:
        self.calls.append(
            evaluated_at
        )

        if self.scheduler is not None:
            self.state_seen_during_call = (
                self.scheduler.state
            )

        return ForceExitBatch(
            force_exit_time_reached=(
                self.batch_force_exit_reached
            ),
            instructions=(),
            evaluated_at=evaluated_at,
        )


class ExplodingForceExitCoordinator(
    FakeForceExitCoordinator
):
    def evaluate_all(
        self,
        *,
        evaluated_at: datetime,
    ) -> ForceExitBatch:
        raise RuntimeError(
            "M07 unavailable"
        )


class InvalidBatchForceExitCoordinator(
    FakeForceExitCoordinator
):
    def evaluate_all(
        self,
        *,
        evaluated_at: datetime,
    ):
        return object()


class WrongTimestampForceExitCoordinator(
    FakeForceExitCoordinator
):
    def evaluate_all(
        self,
        *,
        evaluated_at: datetime,
    ) -> ForceExitBatch:
        return ForceExitBatch(
            force_exit_time_reached=True,
            instructions=(),
            evaluated_at=dt(
                15,
                15,
                1,
            ),
        )


def make_waiting_scheduler() -> TradingDayScheduler:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=dt(
            8,
            30,
        ),
    )

    scheduler.start(
        started_at=dt(
            9,
            0,
        )
    )

    return scheduler


def make_monitoring_scheduler() -> TradingDayScheduler:
    scheduler = make_waiting_scheduler()

    scheduler.transition(
        target_state=(
            TradingDayState
            .WAITING_FOR_REFERENCE_CLOSE
        ),
        transitioned_at=dt(
            9,
            15,
        ),
    )

    scheduler.transition(
        target_state=(
            TradingDayState
            .SELECTING_OPTIONS
        ),
        transitioned_at=dt(
            9,
            16,
        ),
    )

    scheduler.transition(
        target_state=(
            TradingDayState
            .PREPARING_LEVELS
        ),
        transitioned_at=dt(
            9,
            16,
            1,
        ),
    )

    scheduler.transition(
        target_state=(
            TradingDayState
            .WAITING_FOR_MONITORING
        ),
        transitioned_at=dt(
            9,
            17,
        ),
    )

    scheduler.transition(
        target_state=TradingDayState.MONITORING,
        transitioned_at=dt(
            9,
            21,
        ),
    )

    return scheduler


def test_default_force_exit_time_is_1515() -> None:
    assert (
        ForceExitWindowSchedule()
        .force_exit_time
        == time(
            15,
            15,
        )
    )


def test_m10_and_m07_force_exit_times_must_match() -> None:
    scheduler = make_monitoring_scheduler()

    with pytest.raises(
        ValueError,
        match=(
            "M10 and M07 force-exit times must match"
        ),
    ):
        TradingDayForceExitCoordinator(
            scheduler=scheduler,
            force_exit_coordinator=(
                FakeForceExitCoordinator(
                    force_exit_time=time(
                        15,
                        16,
                    )
                )
            ),
        )


def test_before_1515_does_not_transition_or_call_m07() -> None:
    scheduler = make_monitoring_scheduler()

    m07 = FakeForceExitCoordinator(
        scheduler=scheduler
    )

    result = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=m07,
    ).coordinate(
        evaluated_at=dt(
            15,
            14,
            59,
        )
    )

    assert result.force_exit_due is False

    assert (
        result.transitioned_to_exit_only
        is False
    )

    assert result.batch is None

    assert (
        scheduler.state
        is TradingDayState.MONITORING
    )

    assert m07.calls == []


def test_exactly_1515_transitions_to_exit_only_before_m07() -> None:
    scheduler = make_monitoring_scheduler()

    m07 = FakeForceExitCoordinator(
        scheduler=scheduler
    )

    result = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=m07,
    ).coordinate(
        evaluated_at=dt(
            15,
            15,
        )
    )

    assert result.force_exit_due is True

    assert (
        result.transitioned_to_exit_only
        is True
    )

    assert (
        result.snapshot.state
        is TradingDayState.EXIT_ONLY
    )

    assert (
        result.snapshot.can_accept_new_entries
        is False
    )

    assert (
        result.snapshot.can_manage_positions
        is True
    )

    assert (
        m07.state_seen_during_call
        is TradingDayState.EXIT_ONLY
    )

    assert m07.calls == [
        dt(
            15,
            15,
        )
    ]


def test_incomplete_morning_state_can_enter_exit_only() -> None:
    scheduler = make_waiting_scheduler()

    assert (
        scheduler.state
        is TradingDayState.WAITING_FOR_MARKET
    )

    m07 = FakeForceExitCoordinator(
        scheduler=scheduler
    )

    result = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=m07,
    ).coordinate(
        evaluated_at=dt(
            15,
            15,
        )
    )

    assert result.force_exit_due is True

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )

    assert (
        m07.state_seen_during_call
        is TradingDayState.EXIT_ONLY
    )


def test_after_1515_existing_exit_only_is_idempotent() -> None:
    scheduler = make_monitoring_scheduler()

    m07 = FakeForceExitCoordinator(
        scheduler=scheduler
    )

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=m07,
    )

    first = coordinator.coordinate(
        evaluated_at=dt(
            15,
            15,
        )
    )

    second = coordinator.coordinate(
        evaluated_at=dt(
            15,
            16,
        )
    )

    assert (
        first.transitioned_to_exit_only
        is True
    )

    assert (
        second.transitioned_to_exit_only
        is False
    )

    assert (
        second.snapshot.state
        is TradingDayState.EXIT_ONLY
    )

    assert m07.calls == [
        dt(
            15,
            15,
        ),
        dt(
            15,
            16,
        ),
    ]


def test_is_force_exit_due_boundary() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=(
            FakeForceExitCoordinator()
        ),
    )

    assert (
        coordinator.is_force_exit_due(
            dt(
                15,
                14,
                59,
            )
        )
        is False
    )

    assert (
        coordinator.is_force_exit_due(
            dt(
                15,
                15,
            )
        )
        is True
    )


def test_wrong_trading_date_is_rejected() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=(
            FakeForceExitCoordinator()
        ),
    )

    with pytest.raises(
        TradingDayForceExitError,
        match=(
            "force-exit timestamp does not match "
            "scheduler trading_date"
        ),
    ):
        coordinator.coordinate(
            evaluated_at=dt(
                15,
                15,
                day=11,
            )
        )


def test_non_datetime_is_rejected() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=(
            FakeForceExitCoordinator()
        ),
    )

    with pytest.raises(
        TypeError,
        match=(
            "force-exit timestamp must be a datetime"
        ),
    ):
        coordinator.coordinate(
            evaluated_at=object()
        )


def test_m07_failure_leaves_scheduler_exit_only() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=(
            ExplodingForceExitCoordinator()
        ),
    )

    with pytest.raises(
        TradingDayForceExitError,
        match=(
            "M07 force-exit evaluation failed"
        ),
    ):
        coordinator.coordinate(
            evaluated_at=dt(
                15,
                15,
            )
        )

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )

    assert (
        scheduler.snapshot
        .can_accept_new_entries
        is False
    )


def test_invalid_m07_result_fails_closed_in_exit_only() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=(
            InvalidBatchForceExitCoordinator()
        ),
    )

    with pytest.raises(
        TradingDayForceExitError,
        match=(
            "must return ForceExitBatch"
        ),
    ):
        coordinator.coordinate(
            evaluated_at=dt(
                15,
                15,
            )
        )

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )


def test_m07_must_confirm_force_exit_time() -> None:
    scheduler = make_monitoring_scheduler()

    m07 = FakeForceExitCoordinator()

    m07.batch_force_exit_reached = False

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=m07,
    )

    with pytest.raises(
        TradingDayForceExitError,
        match=(
            "did not confirm force-exit time"
        ),
    ):
        coordinator.coordinate(
            evaluated_at=dt(
                15,
                15,
            )
        )

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )


def test_m07_batch_timestamp_must_match() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=(
            WrongTimestampForceExitCoordinator()
        ),
    )

    with pytest.raises(
        TradingDayForceExitError,
        match=(
            "batch timestamp mismatch"
        ),
    ):
        coordinator.coordinate(
            evaluated_at=dt(
                15,
                15,
            )
        )

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )


def test_created_state_cannot_skip_startup_at_1515() -> None:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=dt(
            8,
            30,
        ),
    )

    m07 = FakeForceExitCoordinator()

    coordinator = TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=m07,
    )

    with pytest.raises(
        TradingDayForceExitError,
        match=(
            "requires an active trading-day state "
            "or EXIT_ONLY"
        ),
    ):
        coordinator.coordinate(
            evaluated_at=dt(
                15,
                15,
            )
        )

    assert (
        scheduler.state
        is TradingDayState.CREATED
    )

    assert m07.calls == []
