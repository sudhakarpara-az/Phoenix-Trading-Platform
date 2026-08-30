from __future__ import annotations

from datetime import datetime

import pytest

from src.api.operator_control import (
    OperatorControlService,
    OperatorControlStateView,
    OperatorExitAndStopView,
)
from src.app.trading_control import (
    ExitAndStopCommandResult,
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
    14,
    30,
)


class FakeCommands:
    def __init__(
        self,
        *,
        stop_result: ExitAndStopCommandResult,
        resume_result: TradingControlSnapshot,
    ) -> None:
        self.stop_result = stop_result
        self.resume_result = (
            resume_result
        )

        self.stop_calls = 0
        self.resume_calls = 0

        self.last_stop_time: (
            datetime | None
        ) = None

        self.last_resume_time: (
            datetime | None
        ) = None

        self.last_message: (
            str | None
        ) = None

    def exit_and_stop(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> ExitAndStopCommandResult:
        self.stop_calls += 1
        self.last_stop_time = changed_at
        self.last_message = message

        return self.stop_result

    def resume(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        self.resume_calls += 1
        self.last_resume_time = (
            changed_at
        )
        self.last_message = message

        return self.resume_result


def make_stop_result(
    *,
    readiness: (
        TradingDayCloseReadiness
        | None
    ) = None,
    entry_error: str | None = None,
    liquidation_error: str | None = None,
    readiness_error: str | None = None,
) -> ExitAndStopCommandResult:
    if readiness is None:
        readiness = (
            TradingDayCloseReadiness(
                open_position_count=0,
                unresolved_order_count=0,
            )
        )

    control = TradingControlSnapshot(
        broker="DHAN",
        account_id="TEST-ACCOUNT",
        state=(
            TradingControlState
            .EXIT_AND_STOP
        ),
        changed_at=NOW,
        message="operator stop",
    )

    return ExitAndStopCommandResult(
        control=control,
        entry_results=(
            object(),
            object(),
        ),
        liquidation_results=(
            object(),
        ),
        readiness=readiness,
        requested_at=NOW,
        entry_error=entry_error,
        liquidation_error=(
            liquidation_error
        ),
        readiness_error=(
            readiness_error
        ),
    )


def make_service(
    *,
    stop_result: (
        ExitAndStopCommandResult
        | None
    ) = None,
):
    resolved_stop = (
        make_stop_result()
        if stop_result is None
        else stop_result
    )

    resume_result = (
        TradingControlSnapshot(
            broker="DHAN",
            account_id="TEST-ACCOUNT",
            state=(
                TradingControlState.ACTIVE
            ),
            changed_at=NOW,
            message="resume",
        )
    )

    commands = FakeCommands(
        stop_result=resolved_stop,
        resume_result=resume_result,
    )

    service = OperatorControlService(
        commands=commands
    )

    return (
        service,
        commands,
    )


def test_constructor_preserves_exact_command_owner() -> None:
    service, commands = make_service()

    assert (
        service.commands
        is commands
    )


def test_exit_and_stop_delegates_once_and_maps_safe_view() -> None:
    service, commands = make_service()

    result = service.exit_and_stop(
        requested_at=NOW,
        message="operator stop",
    )

    assert isinstance(
        result,
        OperatorExitAndStopView,
    )

    assert commands.stop_calls == 1
    assert commands.last_stop_time == NOW

    assert (
        commands.last_message
        == "operator stop"
    )

    assert (
        result.control.state
        == "EXIT_AND_STOP"
    )

    assert (
        result.control
        .new_entries_allowed
        is False
    )

    assert (
        result.flat_confirmed
        is True
    )

    assert (
        result.requires_attention
        is False
    )

    assert (
        result.pending_entry_result_count
        == 2
    )

    assert (
        result.liquidation_result_count
        == 1
    )

    assert (
        result.open_position_count
        == 0
    )

    assert (
        result.unresolved_order_count
        == 0
    )

    # Raw internal M10 result tuples are deliberately absent.
    assert not hasattr(
        result,
        "entry_results",
    )

    assert not hasattr(
        result,
        "liquidation_results",
    )


def test_exit_and_stop_projects_sanitized_phase_status() -> None:
    stop_result = make_stop_result(
        entry_error=(
            "pending BUY cancellation "
            "failed: RuntimeError"
        ),
        readiness_error=(
            "flatness verification "
            "failed: RuntimeError"
        ),
    )

    stop_result = ExitAndStopCommandResult(
        control=stop_result.control,
        entry_results=(
            stop_result.entry_results
        ),
        liquidation_results=(
            stop_result
            .liquidation_results
        ),
        readiness=None,
        requested_at=(
            stop_result.requested_at
        ),
        entry_error=(
            stop_result.entry_error
        ),
        liquidation_error=None,
        readiness_error=(
            stop_result.readiness_error
        ),
    )

    service, _ = make_service(
        stop_result=stop_result
    )

    result = service.exit_and_stop(
        requested_at=NOW
    )

    assert (
        result.flat_confirmed
        is False
    )

    assert (
        result.requires_attention
        is True
    )

    assert (
        result.open_position_count
        is None
    )

    assert (
        result.unresolved_order_count
        is None
    )

    assert (
        result.entry_error
        == (
            "pending BUY cancellation "
            "failed: RuntimeError"
        )
    )

    assert (
        result.readiness_error
        == (
            "flatness verification "
            "failed: RuntimeError"
        )
    )


def test_resume_delegates_once_and_maps_active_state() -> None:
    service, commands = make_service()

    result = service.resume(
        requested_at=NOW,
        message="resume trading",
    )

    assert isinstance(
        result,
        OperatorControlStateView,
    )

    assert commands.resume_calls == 1

    assert (
        commands.last_resume_time
        == NOW
    )

    assert (
        commands.last_message
        == "resume trading"
    )

    assert result.state == "ACTIVE"

    assert (
        result.new_entries_allowed
        is True
    )


def test_invalid_requested_at_is_rejected_before_delegate() -> None:
    service, commands = make_service()

    with pytest.raises(
        TypeError,
        match=(
            "requested_at must be datetime"
        ),
    ):
        service.exit_and_stop(
            requested_at="invalid",  # type: ignore[arg-type]
        )

    assert commands.stop_calls == 0


def test_invalid_message_is_rejected_before_delegate() -> None:
    service, commands = make_service()

    with pytest.raises(
        TypeError,
        match=(
            "message must be str or None"
        ),
    ):
        service.resume(
            requested_at=NOW,
            message=123,  # type: ignore[arg-type]
        )

    assert commands.resume_calls == 0
