"""
M10-T12 end-of-day closure and trading-day rollover.
"""

from datetime import date, datetime

import pytest

from src.services.scheduler import (
    TradingCalendar,
    TradingDayCloseReadiness,
    TradingDayEndOfDayCoordinator,
    TradingDayEndOfDayError,
    TradingDayRolloverCoordinator,
    TradingDayRolloverError,
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


class FakeReadinessProvider:
    def __init__(
        self,
        *,
        open_positions: int = 0,
        unresolved_orders: int = 0,
    ) -> None:
        self.open_positions = open_positions
        self.unresolved_orders = unresolved_orders

        self.calls: list[
            datetime
        ] = []

    def evaluate_close_readiness(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayCloseReadiness:
        self.calls.append(
            evaluated_at
        )

        return TradingDayCloseReadiness(
            open_position_count=(
                self.open_positions
            ),
            unresolved_order_count=(
                self.unresolved_orders
            ),
        )


class ExplodingReadinessProvider:
    def evaluate_close_readiness(
        self,
        *,
        evaluated_at: datetime,
    ):
        del evaluated_at

        raise RuntimeError(
            "readiness unavailable"
        )


class InvalidReadinessProvider:
    def evaluate_close_readiness(
        self,
        *,
        evaluated_at: datetime,
    ):
        del evaluated_at

        return object()


def make_exit_only_scheduler(
    *,
    exit_only_at: datetime | None = None,
    calendar: TradingCalendar | None = None,
) -> TradingDayScheduler:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=dt(
            8,
            30,
        ),
        calendar=calendar,
    )

    scheduler.start(
        started_at=dt(
            9,
            0,
        )
    )

    scheduler.transition(
        target_state=TradingDayState.EXIT_ONLY,
        transitioned_at=(
            exit_only_at
            or dt(
                15,
                15,
            )
        ),
    )

    return scheduler


def close_scheduler(
    *,
    calendar: TradingCalendar | None = None,
) -> TradingDayScheduler:
    scheduler = make_exit_only_scheduler(
        calendar=calendar
    )

    result = TradingDayEndOfDayCoordinator(
        scheduler=scheduler,
        readiness_provider=(
            FakeReadinessProvider()
        ),
    ).evaluate(
        evaluated_at=dt(
            15,
            20,
        )
    )

    assert result.complete is True

    return scheduler


def test_close_readiness_requires_non_negative_ints() -> None:
    with pytest.raises(
        ValueError,
        match="open_position_count",
    ):
        TradingDayCloseReadiness(
            open_position_count=-1,
            unresolved_order_count=0,
        )

    with pytest.raises(
        ValueError,
        match="unresolved_order_count",
    ):
        TradingDayCloseReadiness(
            open_position_count=0,
            unresolved_order_count=True,
        )


def test_close_readiness_is_ready_only_when_both_zero() -> None:
    assert TradingDayCloseReadiness(
        open_position_count=0,
        unresolved_order_count=0,
    ).is_ready is True

    assert TradingDayCloseReadiness(
        open_position_count=1,
        unresolved_order_count=0,
    ).is_ready is False

    assert TradingDayCloseReadiness(
        open_position_count=0,
        unresolved_order_count=1,
    ).is_ready is False


def test_eod_requires_exit_only_state() -> None:
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

    with pytest.raises(
        TradingDayEndOfDayError,
        match="requires EXIT_ONLY",
    ):
        TradingDayEndOfDayCoordinator(
            scheduler=scheduler,
            readiness_provider=(
                FakeReadinessProvider()
            ),
        ).evaluate(
            evaluated_at=dt(
                15,
                20,
            )
        )


def test_eod_cannot_close_before_1515() -> None:
    scheduler = make_exit_only_scheduler(
        exit_only_at=dt(
            15,
            14,
        )
    )

    provider = FakeReadinessProvider()

    with pytest.raises(
        TradingDayEndOfDayError,
        match="before force-exit time",
    ):
        TradingDayEndOfDayCoordinator(
            scheduler=scheduler,
            readiness_provider=provider,
        ).evaluate(
            evaluated_at=dt(
                15,
                14,
                30,
            )
        )

    assert provider.calls == []

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )


def test_open_position_blocks_close() -> None:
    scheduler = make_exit_only_scheduler()

    provider = FakeReadinessProvider(
        open_positions=1,
    )

    result = TradingDayEndOfDayCoordinator(
        scheduler=scheduler,
        readiness_provider=provider,
    ).evaluate(
        evaluated_at=dt(
            15,
            20,
        )
    )

    assert result.complete is False

    assert (
        result.transitioned_to_closed
        is False
    )

    assert result.readiness is not None

    assert (
        result.readiness.open_position_count
        == 1
    )

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )

    assert (
        scheduler.snapshot.can_manage_positions
        is True
    )


def test_unresolved_order_blocks_close() -> None:
    scheduler = make_exit_only_scheduler()

    result = TradingDayEndOfDayCoordinator(
        scheduler=scheduler,
        readiness_provider=(
            FakeReadinessProvider(
                unresolved_orders=1,
            )
        ),
    ).evaluate(
        evaluated_at=dt(
            15,
            20,
        )
    )

    assert result.complete is False

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )


def test_zero_exposure_and_orders_closes_day() -> None:
    scheduler = make_exit_only_scheduler()

    provider = FakeReadinessProvider()

    result = TradingDayEndOfDayCoordinator(
        scheduler=scheduler,
        readiness_provider=provider,
    ).evaluate(
        evaluated_at=dt(
            15,
            20,
        )
    )

    assert result.complete is True

    assert (
        result.transitioned_to_closed
        is True
    )

    assert (
        result.snapshot.state
        is TradingDayState.CLOSED
    )

    assert (
        result.snapshot.closed_at
        == dt(
            15,
            20,
        )
    )

    assert (
        result.snapshot.can_accept_new_entries
        is False
    )

    assert (
        result.snapshot.can_manage_positions
        is False
    )

    assert result.snapshot.is_terminal is True


def test_readiness_failure_keeps_exit_only() -> None:
    scheduler = make_exit_only_scheduler()

    with pytest.raises(
        TradingDayEndOfDayError,
        match="readiness evaluation failed",
    ):
        TradingDayEndOfDayCoordinator(
            scheduler=scheduler,
            readiness_provider=(
                ExplodingReadinessProvider()
            ),
        ).evaluate(
            evaluated_at=dt(
                15,
                20,
            )
        )

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )


def test_invalid_readiness_result_fails_closed() -> None:
    scheduler = make_exit_only_scheduler()

    with pytest.raises(
        TradingDayEndOfDayError,
        match=(
            "must return TradingDayCloseReadiness"
        ),
    ):
        TradingDayEndOfDayCoordinator(
            scheduler=scheduler,
            readiness_provider=(
                InvalidReadinessProvider()
            ),
        ).evaluate(
            evaluated_at=dt(
                15,
                20,
            )
        )

    assert (
        scheduler.state
        is TradingDayState.EXIT_ONLY
    )


def test_eod_rejects_wrong_trading_date() -> None:
    scheduler = make_exit_only_scheduler()

    with pytest.raises(
        TradingDayEndOfDayError,
        match="scheduler trading_date",
    ):
        TradingDayEndOfDayCoordinator(
            scheduler=scheduler,
            readiness_provider=(
                FakeReadinessProvider()
            ),
        ).evaluate(
            evaluated_at=dt(
                15,
                20,
                day=11,
            )
        )


def test_eod_rejects_non_datetime() -> None:
    scheduler = make_exit_only_scheduler()

    with pytest.raises(
        TypeError,
        match="must be a datetime",
    ):
        TradingDayEndOfDayCoordinator(
            scheduler=scheduler,
            readiness_provider=(
                FakeReadinessProvider()
            ),
        ).evaluate(
            evaluated_at=object()
        )


def test_closed_eod_is_idempotent_without_rechecking_provider() -> None:
    scheduler = make_exit_only_scheduler()

    provider = FakeReadinessProvider()

    coordinator = TradingDayEndOfDayCoordinator(
        scheduler=scheduler,
        readiness_provider=provider,
    )

    first = coordinator.evaluate(
        evaluated_at=dt(
            15,
            20,
        )
    )

    second = coordinator.evaluate(
        evaluated_at=dt(
            15,
            21,
        )
    )

    assert first.complete is True

    assert second.complete is True

    assert (
        second.transitioned_to_closed
        is False
    )

    assert second.readiness is None

    assert provider.calls == [
        dt(
            15,
            20,
        )
    ]


def test_calendar_next_trading_day_normal_weekday() -> None:
    calendar = TradingCalendar()

    assert calendar.next_trading_day(
        date(
            2026,
            8,
            10,
        )
    ) == date(
        2026,
        8,
        11,
    )


def test_calendar_next_trading_day_skips_weekend() -> None:
    calendar = TradingCalendar()

    assert calendar.next_trading_day(
        date(
            2026,
            8,
            14,
        )
    ) == date(
        2026,
        8,
        17,
    )


def test_calendar_next_trading_day_skips_holiday() -> None:
    calendar = TradingCalendar(
        holidays=frozenset(
            {
                date(
                    2026,
                    8,
                    11,
                )
            }
        )
    )

    assert calendar.next_trading_day(
        TRADING_DATE
    ) == date(
        2026,
        8,
        12,
    )


def test_rollover_requires_closed_day() -> None:
    scheduler = make_exit_only_scheduler()

    with pytest.raises(
        TradingDayRolloverError,
        match="requires CLOSED",
    ):
        TradingDayRolloverCoordinator(
            scheduler=scheduler
        ).create_next_scheduler(
            created_at=dt(
                15,
                30,
            )
        )


def test_rollover_creates_fresh_next_trading_day_scheduler() -> None:
    scheduler = close_scheduler()

    next_scheduler = (
        TradingDayRolloverCoordinator(
            scheduler=scheduler
        )
        .create_next_scheduler(
            created_at=dt(
                15,
                30,
            )
        )
    )

    assert (
        next_scheduler.trading_date
        == date(
            2026,
            8,
            11,
        )
    )

    assert (
        next_scheduler.state
        is TradingDayState.CREATED
    )

    assert (
        next_scheduler.calendar
        is scheduler.calendar
    )

    assert (
        next_scheduler
        is not scheduler
    )


def test_rollover_skips_holiday_and_weekend() -> None:
    friday = date(
        2026,
        8,
        14,
    )

    monday_holiday = date(
        2026,
        8,
        17,
    )

    calendar = TradingCalendar(
        holidays=frozenset(
            {
                monday_holiday,
            }
        )
    )

    scheduler = TradingDayScheduler(
        trading_date=friday,
        created_at=datetime(
            2026,
            8,
            14,
            8,
            30,
        ),
        calendar=calendar,
    )

    scheduler.start(
        started_at=datetime(
            2026,
            8,
            14,
            9,
            0,
        )
    )

    scheduler.transition(
        target_state=TradingDayState.EXIT_ONLY,
        transitioned_at=datetime(
            2026,
            8,
            14,
            15,
            15,
        ),
    )

    TradingDayEndOfDayCoordinator(
        scheduler=scheduler,
        readiness_provider=(
            FakeReadinessProvider()
        ),
    ).evaluate(
        evaluated_at=datetime(
            2026,
            8,
            14,
            15,
            20,
        )
    )

    next_scheduler = (
        TradingDayRolloverCoordinator(
            scheduler=scheduler
        )
        .create_next_scheduler(
            created_at=datetime(
                2026,
                8,
                14,
                15,
                30,
            )
        )
    )

    assert (
        next_scheduler.trading_date
        == date(
            2026,
            8,
            18,
        )
    )


def test_rollover_is_idempotent() -> None:
    scheduler = close_scheduler()

    coordinator = TradingDayRolloverCoordinator(
        scheduler=scheduler
    )

    first = coordinator.create_next_scheduler(
        created_at=dt(
            15,
            30,
        )
    )

    second = coordinator.create_next_scheduler(
        created_at=dt(
            15,
            31,
        )
    )

    assert second is first

    assert (
        coordinator.created_next_scheduler
        is first
    )


def test_rollover_created_at_cannot_precede_close() -> None:
    scheduler = close_scheduler()

    with pytest.raises(
        TradingDayRolloverError,
        match="cannot be before closed_at",
    ):
        TradingDayRolloverCoordinator(
            scheduler=scheduler
        ).create_next_scheduler(
            created_at=dt(
                15,
                19,
            )
        )
