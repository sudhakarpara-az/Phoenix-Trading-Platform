"""
M10-T10 trading-day + runtime new-entry orchestration gate.
"""

from datetime import date, datetime

import pytest

from src.services.scheduler import (
    TradingDayEntryGateCoordinator,
    TradingDayEntryGateError,
    TradingDayEntryGateReason,
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


class FakeRuntimeEntryGate:
    def __init__(
        self,
        allowed: bool = True,
    ) -> None:
        self.allowed = allowed
        self.calls = 0

    def can_accept_new_entries(
        self,
    ) -> bool:
        self.calls += 1
        return self.allowed


class ExplodingRuntimeEntryGate:
    def can_accept_new_entries(
        self,
    ) -> bool:
        raise RuntimeError(
            "runtime unavailable"
        )


class InvalidRuntimeEntryGate:
    def can_accept_new_entries(
        self,
    ):
        return 1


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

    return scheduler


def make_monitoring_scheduler() -> TradingDayScheduler:
    scheduler = make_waiting_scheduler()

    scheduler.transition(
        target_state=TradingDayState.MONITORING,
        transitioned_at=dt(
            9,
            21,
        ),
    )

    return scheduler


def test_pre_monitoring_state_blocks_before_runtime_gate() -> None:
    scheduler = make_waiting_scheduler()
    runtime = FakeRuntimeEntryGate(
        allowed=True
    )

    decision = TradingDayEntryGateCoordinator(
        scheduler=scheduler,
        runtime_gate=runtime,
    ).evaluate(
        evaluated_at=dt(
            9,
            20,
            59,
        )
    )

    assert decision.allowed is False

    assert (
        decision.reason
        is TradingDayEntryGateReason.TRADING_DAY_BLOCKED
    )

    assert decision.scheduler_allowed is False
    assert decision.runtime_allowed is None

    assert runtime.calls == 0


def test_monitoring_and_runtime_allowed_permits_candidate() -> None:
    scheduler = make_monitoring_scheduler()
    runtime = FakeRuntimeEntryGate(
        allowed=True
    )

    decision = TradingDayEntryGateCoordinator(
        scheduler=scheduler,
        runtime_gate=runtime,
    ).evaluate(
        evaluated_at=dt(
            9,
            21,
        )
    )

    assert decision.allowed is True

    assert (
        decision.reason
        is TradingDayEntryGateReason.ALLOWED
    )

    assert decision.scheduler_allowed is True
    assert decision.runtime_allowed is True

    assert runtime.calls == 1


def test_runtime_gate_can_block_while_scheduler_is_monitoring() -> None:
    scheduler = make_monitoring_scheduler()
    runtime = FakeRuntimeEntryGate(
        allowed=False
    )

    decision = TradingDayEntryGateCoordinator(
        scheduler=scheduler,
        runtime_gate=runtime,
    ).evaluate(
        evaluated_at=dt(
            10,
            0,
        )
    )

    assert decision.allowed is False

    assert (
        decision.reason
        is TradingDayEntryGateReason.RUNTIME_BLOCKED
    )

    assert decision.scheduler_allowed is True
    assert decision.runtime_allowed is False

    assert runtime.calls == 1


def test_exit_only_blocks_before_runtime_gate() -> None:
    scheduler = make_monitoring_scheduler()

    scheduler.transition(
        target_state=TradingDayState.EXIT_ONLY,
        transitioned_at=dt(
            15,
            15,
        ),
    )

    runtime = FakeRuntimeEntryGate(
        allowed=True
    )

    decision = TradingDayEntryGateCoordinator(
        scheduler=scheduler,
        runtime_gate=runtime,
    ).evaluate(
        evaluated_at=dt(
            15,
            15,
        )
    )

    assert decision.allowed is False

    assert (
        decision.reason
        is TradingDayEntryGateReason.TRADING_DAY_BLOCKED
    )

    assert runtime.calls == 0


def test_wrong_trading_date_is_rejected() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayEntryGateCoordinator(
        scheduler=scheduler,
        runtime_gate=FakeRuntimeEntryGate(),
    )

    with pytest.raises(
        ValueError,
        match=(
            "evaluated_at must belong to "
            "scheduler trading_date"
        ),
    ):
        coordinator.evaluate(
            evaluated_at=dt(
                10,
                0,
                day=11,
            )
        )


def test_non_datetime_is_rejected() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayEntryGateCoordinator(
        scheduler=scheduler,
        runtime_gate=FakeRuntimeEntryGate(),
    )

    with pytest.raises(
        TypeError,
        match=(
            "evaluated_at must be a datetime"
        ),
    ):
        coordinator.evaluate(
            evaluated_at=object()
        )


def test_runtime_gate_failure_fails_closed() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayEntryGateCoordinator(
        scheduler=scheduler,
        runtime_gate=ExplodingRuntimeEntryGate(),
    )

    with pytest.raises(
        TradingDayEntryGateError,
        match=(
            "runtime entry gate evaluation failed"
        ),
    ):
        coordinator.evaluate(
            evaluated_at=dt(
                10,
                0,
            )
        )


def test_runtime_gate_must_return_bool() -> None:
    scheduler = make_monitoring_scheduler()

    coordinator = TradingDayEntryGateCoordinator(
        scheduler=scheduler,
        runtime_gate=InvalidRuntimeEntryGate(),
    )

    with pytest.raises(
        TradingDayEntryGateError,
        match=(
            "runtime entry gate must return bool"
        ),
    ):
        coordinator.evaluate(
            evaluated_at=dt(
                10,
                0,
            )
        )
