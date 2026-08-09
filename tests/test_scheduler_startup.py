"""
Tests for Phoenix M10 startup/recovery coordination.
"""

from datetime import date, datetime

import pytest

from src.runtime.event_bus import RuntimeEventBus
from src.runtime.recovery_types import (
    StartupRecoveryPlan,
    StartupRecoveryResult,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeFailureCode,
    RuntimeId,
    RuntimeMode,
    RuntimeState,
)
from src.services.scheduler import (
    TradingCalendar,
    TradingDayScheduler,
    TradingDayStartupCoordinator,
    TradingDayStartupError,
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

STARTED_AT = datetime(
    2026,
    8,
    10,
    9,
    0,
)

RECOVERY_AT = datetime(
    2026,
    8,
    10,
    9,
    1,
)

RUNNING_AT = datetime(
    2026,
    8,
    10,
    9,
    2,
)


def clean_plan() -> StartupRecoveryPlan:
    return StartupRecoveryPlan(
        source_runtime_id=None,
        persisted_runtime_state=None,
        unresolved_order_count=0,
        open_position_count=0,
        recovery_required=False,
    )


def recovery_plan() -> StartupRecoveryPlan:
    return StartupRecoveryPlan(
        source_runtime_id="OLD-RUNTIME",
        persisted_runtime_state="RUNNING",
        unresolved_order_count=1,
        open_position_count=1,
        recovery_required=True,
    )


def make_scheduler(
    *,
    trading_date: date = TRADING_DATE,
    calendar: TradingCalendar | None = None,
) -> TradingDayScheduler:
    return TradingDayScheduler(
        trading_date=trading_date,
        created_at=datetime.combine(
            trading_date,
            CREATED_AT.time(),
        ),
        calendar=calendar,
    )


def make_runtime(
    *,
    recovery_required: bool,
    trading_date: date = TRADING_DATE,
) -> TradingRuntimeOrchestrator:
    return TradingRuntimeOrchestrator(
        runtime_id=RuntimeId(
            "CURRENT-RUNTIME"
        ),
        trading_date=trading_date,
        mode=RuntimeMode.DRY_RUN,
        event_bus=RuntimeEventBus(),
        created_at=datetime.combine(
            trading_date,
            CREATED_AT.time(),
        ),
        recovery_required=recovery_required,
    )


class FakeRecoveryService:
    def __init__(
        self,
        *,
        plan: StartupRecoveryPlan,
        recovery_completes: bool = True,
    ) -> None:
        self.plan = plan
        self.recovery_completes = (
            recovery_completes
        )

        self.build_dates: list[date] = []
        self.recover_calls: list[
            tuple[str, datetime]
        ] = []

    def build_plan(
        self,
        *,
        trading_date: date,
    ) -> StartupRecoveryPlan:
        self.build_dates.append(
            trading_date
        )

        return self.plan

    def recover(
        self,
        *,
        orchestrator: TradingRuntimeOrchestrator,
        source_runtime_id: str,
        checked_at: datetime,
    ) -> StartupRecoveryResult:
        self.recover_calls.append(
            (
                source_runtime_id,
                checked_at,
            )
        )

        if self.recovery_completes:
            orchestrator.complete_recovery(
                completed_at=checked_at
            )

            return StartupRecoveryResult(
                source_runtime_id=source_runtime_id,
                recovered_orders=1,
                recovered_positions=1,
                issues=(),
                completed=True,
            )

        orchestrator.fail(
            code=RuntimeFailureCode.RECOVERY_FAILED,
            message="recovery failed",
            failed_at=checked_at,
            component="startup-recovery",
            recoverable=True,
        )

        return StartupRecoveryResult(
            source_runtime_id=source_runtime_id,
            recovered_orders=0,
            recovered_positions=0,
            issues=(),
            completed=False,
        )


def test_coordinator_builds_plan_for_scheduler_date() -> None:
    scheduler = make_scheduler()

    recovery = FakeRecoveryService(
        plan=clean_plan()
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    plan = coordinator.build_recovery_plan()

    assert plan.recovery_required is False
    assert recovery.build_dates == [
        TRADING_DATE,
    ]


def test_clean_start_reaches_running_runtime() -> None:
    scheduler = make_scheduler()

    recovery = FakeRecoveryService(
        plan=clean_plan()
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    runtime = make_runtime(
        recovery_required=False
    )

    result = coordinator.start(
        orchestrator=runtime,
        recovery_plan=clean_plan(),
        started_at=STARTED_AT,
        recovery_checked_at=RECOVERY_AT,
        running_at=RUNNING_AT,
    )

    assert (
        result.trading_day.state
        is TradingDayState.WAITING_FOR_MARKET
    )

    assert (
        result.runtime.state
        is RuntimeState.RUNNING
    )

    assert result.recovery_result is None
    assert result.is_ready is True
    assert recovery.recover_calls == []


def test_required_recovery_completes_before_running() -> None:
    plan = recovery_plan()

    scheduler = make_scheduler()

    recovery = FakeRecoveryService(
        plan=plan
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    runtime = make_runtime(
        recovery_required=True
    )

    result = coordinator.start(
        orchestrator=runtime,
        recovery_plan=plan,
        started_at=STARTED_AT,
        recovery_checked_at=RECOVERY_AT,
        running_at=RUNNING_AT,
    )

    assert recovery.recover_calls == [
        (
            "OLD-RUNTIME",
            RECOVERY_AT,
        )
    ]

    assert (
        result.runtime.state
        is RuntimeState.RUNNING
    )

    assert result.runtime.recovered is True
    assert result.recovery_result is not None
    assert result.recovery_result.completed is True
    assert result.is_ready is True


def test_failed_recovery_blocks_trading_day() -> None:
    plan = recovery_plan()

    scheduler = make_scheduler()

    recovery = FakeRecoveryService(
        plan=plan,
        recovery_completes=False,
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    runtime = make_runtime(
        recovery_required=True
    )

    result = coordinator.start(
        orchestrator=runtime,
        recovery_plan=plan,
        started_at=STARTED_AT,
        recovery_checked_at=RECOVERY_AT,
        running_at=RUNNING_AT,
    )

    assert (
        result.runtime.state
        is RuntimeState.FAILED
    )

    assert (
        result.trading_day.state
        is TradingDayState.FAILED
    )

    assert result.is_ready is False


def test_non_trading_day_does_not_start_runtime() -> None:
    saturday = date(
        2026,
        8,
        8,
    )

    scheduler = make_scheduler(
        trading_date=saturday
    )

    recovery = FakeRecoveryService(
        plan=clean_plan()
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    runtime = make_runtime(
        recovery_required=False,
        trading_date=saturday,
    )

    started_at = datetime(
        2026,
        8,
        8,
        9,
        0,
    )

    result = coordinator.start(
        orchestrator=runtime,
        recovery_plan=clean_plan(),
        started_at=started_at,
    )

    assert (
        result.trading_day.state
        is TradingDayState.NON_TRADING_DAY
    )

    assert (
        result.runtime.state
        is RuntimeState.CREATED
    )

    assert recovery.recover_calls == []
    assert result.is_ready is False


def test_runtime_date_must_match_scheduler_date() -> None:
    scheduler = make_scheduler()

    recovery = FakeRecoveryService(
        plan=clean_plan()
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    runtime = make_runtime(
        recovery_required=False,
        trading_date=date(
            2026,
            8,
            11,
        ),
    )

    with pytest.raises(
        TradingDayStartupError,
        match=(
            "runtime trading_date does not match "
            "scheduler trading_date"
        ),
    ):
        coordinator.start(
            orchestrator=runtime,
            recovery_plan=clean_plan(),
            started_at=STARTED_AT,
        )

    assert (
        scheduler.state
        is TradingDayState.CREATED
    )


def test_runtime_recovery_flag_must_match_plan() -> None:
    scheduler = make_scheduler()

    recovery = FakeRecoveryService(
        plan=recovery_plan()
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    runtime = make_runtime(
        recovery_required=False
    )

    with pytest.raises(
        TradingDayStartupError,
        match=(
            "runtime recovery_required does not match "
            "recovery plan"
        ),
    ):
        coordinator.start(
            orchestrator=runtime,
            recovery_plan=recovery_plan(),
            started_at=STARTED_AT,
        )

    assert (
        runtime.state
        is RuntimeState.CREATED
    )

    assert (
        scheduler.state
        is TradingDayState.CREATED
    )


def test_recovery_plan_requires_source_runtime_id() -> None:
    invalid_plan = StartupRecoveryPlan(
        source_runtime_id=None,
        persisted_runtime_state="RUNNING",
        unresolved_order_count=1,
        open_position_count=0,
        recovery_required=True,
    )

    scheduler = make_scheduler()

    recovery = FakeRecoveryService(
        plan=invalid_plan
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    runtime = make_runtime(
        recovery_required=True
    )

    with pytest.raises(
        TradingDayStartupError,
        match=(
            "recovery-required plan must provide "
            "source_runtime_id"
        ),
    ):
        coordinator.start(
            orchestrator=runtime,
            recovery_plan=invalid_plan,
            started_at=STARTED_AT,
        )

    assert (
        runtime.state
        is RuntimeState.CREATED
    )


def test_startup_timestamps_must_be_monotonic() -> None:
    scheduler = make_scheduler()

    recovery = FakeRecoveryService(
        plan=clean_plan()
    )

    coordinator = TradingDayStartupCoordinator(
        scheduler=scheduler,
        recovery_service=recovery,
    )

    runtime = make_runtime(
        recovery_required=False
    )

    with pytest.raises(
        TradingDayStartupError,
        match=(
            "recovery_checked_at cannot be before "
            "started_at"
        ),
    ):
        coordinator.start(
            orchestrator=runtime,
            recovery_plan=clean_plan(),
            started_at=STARTED_AT,
            recovery_checked_at=CREATED_AT,
        )

    assert (
        runtime.state
        is RuntimeState.CREATED
    )

    assert (
        scheduler.state
        is TradingDayState.CREATED
    )
