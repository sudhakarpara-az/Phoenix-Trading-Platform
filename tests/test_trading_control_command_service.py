"""
M10 complete EXIT AND STOP command tests.

No live broker, persistence, scheduler transition or runtime
startup is performed here.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.app.trading_control import (
    ExitAndStopCommandResult,
    TradingControlCommandError,
    TradingControlCommandService,
    TradingControlSnapshot,
    TradingControlState,
)
from src.services.scheduler import (
    TradingDayCloseReadiness,
)


NOW = datetime(
    2026,
    8,
    10,
    12,
    0,
)


class FakeControl:
    def __init__(
        self,
        events: list[str],
        *,
        fail_stop: bool = False,
    ) -> None:
        self.events = events
        self.fail_stop = (
            fail_stop
        )

        self.stop_calls = 0
        self.resume_calls = 0

    def activate_exit_and_stop(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        self.events.append(
            "stop"
        )

        self.stop_calls += 1

        if self.fail_stop:
            raise RuntimeError(
                "durable STOP failed"
            )

        return TradingControlSnapshot(
            broker="DHAN",
            account_id="TEST-ACCOUNT",
            state=(
                TradingControlState
                .EXIT_AND_STOP
            ),
            changed_at=changed_at,
            message=message,
        )

    def resume(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        self.events.append(
            "resume"
        )

        self.resume_calls += 1

        return TradingControlSnapshot(
            broker="DHAN",
            account_id="TEST-ACCOUNT",
            state=TradingControlState.ACTIVE,
            changed_at=changed_at,
            message=message,
        )


class FakeEntryRuntime:
    def __init__(
        self,
        events: list[str],
        *,
        fail: bool = False,
    ) -> None:
        self.events = events
        self.fail = fail

    def cancel_pending_entries(
        self,
        *,
        cancelled_at: datetime,
    ) -> tuple[
        object,
        ...,
    ]:
        del cancelled_at

        self.events.append(
            "cancel"
        )

        if self.fail:
            raise RuntimeError(
                "cancel phase failed"
            )

        return (
            "ENTRY-RESULT",
        )


class FakeLiquidationRuntime:
    def __init__(
        self,
        events: list[str],
        *,
        fail: bool = False,
    ) -> None:
        self.events = events
        self.fail = fail

    def liquidate_open_positions(
        self,
        *,
        evaluated_at: datetime,
    ) -> tuple[
        object,
        ...,
    ]:
        del evaluated_at

        self.events.append(
            "liquidate"
        )

        if self.fail:
            raise RuntimeError(
                "liquidation phase failed"
            )

        return (
            "SELL-RESULT",
        )


class FakeReadiness:
    def __init__(
        self,
        events: list[str],
        *,
        ready: bool = True,
        fail: bool = False,
    ) -> None:
        self.events = events
        self.ready = ready
        self.fail = fail

    def evaluate_close_readiness(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayCloseReadiness:
        del evaluated_at

        self.events.append(
            "readiness"
        )

        if self.fail:
            raise RuntimeError(
                "readiness failed"
            )

        count = (
            0
            if self.ready
            else 1
        )

        return TradingDayCloseReadiness(
            open_position_count=count,
            unresolved_order_count=0,
        )


def make_service(
    *,
    fail_stop: bool = False,
    fail_entry: bool = False,
    fail_liquidation: bool = False,
    ready: bool = True,
    fail_readiness: bool = False,
):
    events: list[str] = []

    control = FakeControl(
        events,
        fail_stop=fail_stop,
    )

    entry = FakeEntryRuntime(
        events,
        fail=fail_entry,
    )

    liquidation = (
        FakeLiquidationRuntime(
            events,
            fail=fail_liquidation,
        )
    )

    readiness = FakeReadiness(
        events,
        ready=ready,
        fail=fail_readiness,
    )

    service = (
        TradingControlCommandService(
            trading_control=control,
            entry_runtime=entry,
            liquidation_runtime=(
                liquidation
            ),
            readiness=readiness,
        )
    )

    return (
        service,
        events,
        control,
        entry,
        liquidation,
        readiness,
    )


def test_constructor_preserves_exact_dependencies() -> None:
    (
        service,
        _,
        control,
        entry,
        liquidation,
        readiness,
    ) = make_service()

    assert (
        service.trading_control
        is control
    )

    assert (
        service.entry_runtime
        is entry
    )

    assert (
        service.liquidation_runtime
        is liquidation
    )

    assert (
        service.readiness
        is readiness
    )


def test_exit_and_stop_enforces_required_phase_order() -> None:
    (
        service,
        events,
        _,
        _,
        _,
        _,
    ) = make_service()

    result = service.exit_and_stop(
        changed_at=NOW,
        message="operator requested stop",
    )

    assert isinstance(
        result,
        ExitAndStopCommandResult,
    )

    assert events == [
        "stop",
        "cancel",
        "liquidate",
        "readiness",
    ]

    assert result.stop_active is True
    assert result.flat_confirmed is True

    assert (
        result.requires_attention
        is False
    )

    assert result.entry_results == (
        "ENTRY-RESULT",
    )

    assert (
        result.liquidation_results
        == (
            "SELL-RESULT",
        )
    )

    assert result.entry_error is None

    assert (
        result.liquidation_error
        is None
    )

    assert (
        result.readiness_error
        is None
    )


def test_stop_failure_prevents_all_downstream_actions() -> None:
    (
        service,
        events,
        _,
        _,
        _,
        _,
    ) = make_service(
        fail_stop=True
    )

    with pytest.raises(
        RuntimeError,
        match="durable STOP failed",
    ):
        service.exit_and_stop(
            changed_at=NOW,
        )

    assert events == [
        "stop",
    ]


def test_entry_failure_does_not_skip_liquidation_or_readiness() -> None:
    (
        service,
        events,
        _,
        _,
        _,
        _,
    ) = make_service(
        fail_entry=True
    )

    result = service.exit_and_stop(
        changed_at=NOW,
    )

    assert events == [
        "stop",
        "cancel",
        "liquidate",
        "readiness",
    ]

    assert result.stop_active is True

    assert result.entry_error == (
        "pending BUY cancellation "
        "failed: RuntimeError"
    )

    assert (
        result.liquidation_error
        is None
    )

    assert (
        result.readiness
        is not None
    )

    assert (
        result.requires_attention
        is True
    )


def test_liquidation_failure_still_checks_readiness() -> None:
    (
        service,
        events,
        _,
        _,
        _,
        _,
    ) = make_service(
        fail_liquidation=True
    )

    result = service.exit_and_stop(
        changed_at=NOW,
    )

    assert events == [
        "stop",
        "cancel",
        "liquidate",
        "readiness",
    ]

    assert (
        result.liquidation_error
        == (
            "manual liquidation "
            "failed: RuntimeError"
        )
    )

    assert result.stop_active is True

    assert (
        result.requires_attention
        is True
    )


def test_readiness_failure_is_fail_closed_result() -> None:
    (
        service,
        events,
        _,
        _,
        _,
        _,
    ) = make_service(
        fail_readiness=True
    )

    result = service.exit_and_stop(
        changed_at=NOW,
    )

    assert events == [
        "stop",
        "cancel",
        "liquidate",
        "readiness",
    ]

    assert result.stop_active is True
    assert result.readiness is None

    assert (
        result.flat_confirmed
        is False
    )

    assert (
        result.readiness_error
        == (
            "flatness verification "
            "failed: RuntimeError"
        )
    )

    assert (
        result.requires_attention
        is True
    )


def test_not_flat_keeps_stop_and_requires_attention() -> None:
    (
        service,
        _,
        _,
        _,
        _,
        _,
    ) = make_service(
        ready=False
    )

    result = service.exit_and_stop(
        changed_at=NOW,
    )

    assert result.stop_active is True

    assert (
        result.flat_confirmed
        is False
    )

    assert (
        result.requires_attention
        is True
    )


def test_resume_refuses_when_not_flat() -> None:
    (
        service,
        events,
        control,
        _,
        _,
        _,
    ) = make_service(
        ready=False
    )

    with pytest.raises(
        TradingControlCommandError,
        match=(
            "cannot RESUME while "
            "open positions"
        ),
    ):
        service.resume(
            changed_at=NOW,
        )

    assert events == [
        "readiness",
    ]

    assert control.resume_calls == 0


def test_resume_refuses_when_readiness_cannot_be_proven() -> None:
    (
        service,
        events,
        control,
        _,
        _,
        _,
    ) = make_service(
        fail_readiness=True
    )

    with pytest.raises(
        TradingControlCommandError,
        match=(
            "flatness could not "
            "be established"
        ),
    ):
        service.resume(
            changed_at=NOW,
        )

    assert events == [
        "readiness",
    ]

    assert control.resume_calls == 0


def test_resume_checks_flatness_before_active_transition() -> None:
    (
        service,
        events,
        control,
        _,
        _,
        _,
    ) = make_service(
        ready=True
    )

    snapshot = service.resume(
        changed_at=NOW,
        message="operator resume",
    )

    assert events == [
        "readiness",
        "resume",
    ]

    assert control.resume_calls == 1

    assert (
        snapshot.state
        is TradingControlState.ACTIVE
    )
