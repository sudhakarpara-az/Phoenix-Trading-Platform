from datetime import (
    date,
    datetime,
    timedelta,
)

import pytest

from src.runtime.runtime_types import (
    RuntimeFailure,
    RuntimeFailureCode,
    RuntimeId,
    RuntimeMode,
    RuntimeSnapshot,
    RuntimeState,
)


TRADING_DATE = date(
    2026,
    8,
    8,
)

STARTED_AT = datetime(
    2026,
    8,
    8,
    9,
    0,
)

UPDATED_AT = datetime(
    2026,
    8,
    8,
    9,
    20,
)

STOPPED_AT = datetime(
    2026,
    8,
    8,
    15,
    16,
)


def make_running_snapshot(
    *,
    mode: RuntimeMode = (
        RuntimeMode.DRY_RUN
    ),
) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        runtime_id=RuntimeId(
            "PHOENIX:2026-08-08:TEST"
        ),
        trading_date=TRADING_DATE,
        mode=mode,
        state=RuntimeState.RUNNING,
        started_at=STARTED_AT,
        updated_at=UPDATED_AT,
    )


def test_runtime_id_creation() -> None:
    runtime_id = RuntimeId(
        "PHOENIX:2026-08-08:LIVE"
    )

    assert (
        runtime_id.value
        == "PHOENIX:2026-08-08:LIVE"
    )

    assert (
        str(runtime_id)
        == runtime_id.value
    )


def test_runtime_id_trims_whitespace() -> None:
    runtime_id = RuntimeId(
        "  PHOENIX-001  "
    )

    assert runtime_id.value == "PHOENIX-001"


def test_empty_runtime_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="runtime id cannot be empty",
    ):
        RuntimeId("   ")


def test_runtime_modes() -> None:
    assert (
        RuntimeMode.DRY_RUN.value
        == "DRY_RUN"
    )

    assert (
        RuntimeMode.LIVE.value
        == "LIVE"
    )


def test_runtime_states() -> None:
    assert (
        RuntimeState.CREATED.value
        == "CREATED"
    )

    assert (
        RuntimeState.RECOVERING.value
        == "RECOVERING"
    )

    assert (
        RuntimeState.RUNNING.value
        == "RUNNING"
    )

    assert (
        RuntimeState.FAILED.value
        == "FAILED"
    )


def test_runtime_failure_creation() -> None:
    failure = RuntimeFailure(
        code=(
            RuntimeFailureCode
            .DATABASE_FAILED
        ),
        message="database unavailable",
        occurred_at=UPDATED_AT,
        recoverable=True,
        component="database",
    )

    assert (
        failure.code
        is RuntimeFailureCode
        .DATABASE_FAILED
    )

    assert failure.recoverable is True

    assert (
        failure.component
        == "database"
    )


def test_runtime_failure_message_trimmed() -> None:
    failure = RuntimeFailure(
        code=(
            RuntimeFailureCode
            .INTERNAL_ERROR
        ),
        message="  unexpected failure  ",
        occurred_at=UPDATED_AT,
    )

    assert (
        failure.message
        == "unexpected failure"
    )


def test_empty_failure_message_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "runtime failure message "
            "cannot be empty"
        ),
    ):
        RuntimeFailure(
            code=(
                RuntimeFailureCode
                .INTERNAL_ERROR
            ),
            message=" ",
            occurred_at=UPDATED_AT,
        )


def test_empty_failure_component_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "runtime failure component "
            "cannot be empty"
        ),
    ):
        RuntimeFailure(
            code=(
                RuntimeFailureCode
                .INTERNAL_ERROR
            ),
            message="failure",
            occurred_at=UPDATED_AT,
            component=" ",
        )


def test_created_runtime_snapshot() -> None:
    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "PHOENIX-001"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.DRY_RUN,
        state=RuntimeState.CREATED,
        started_at=None,
        updated_at=UPDATED_AT,
    )

    assert (
        snapshot.state
        is RuntimeState.CREATED
    )

    assert snapshot.started_at is None
    assert snapshot.is_active is False
    assert snapshot.is_terminal is False


def test_starting_runtime_requires_started_at() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "STARTING runtime requires "
            "started_at"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-001"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.DRY_RUN,
            state=RuntimeState.STARTING,
            started_at=None,
            updated_at=UPDATED_AT,
        )


def test_running_runtime() -> None:
    snapshot = make_running_snapshot()

    assert (
        snapshot.state
        is RuntimeState.RUNNING
    )

    assert snapshot.is_active is True
    assert snapshot.is_terminal is False

    assert (
        snapshot.can_process_market_data
        is True
    )

    assert (
        snapshot.can_accept_new_entries
        is True
    )


def test_live_running_runtime() -> None:
    snapshot = make_running_snapshot(
        mode=RuntimeMode.LIVE
    )

    assert (
        snapshot.mode
        is RuntimeMode.LIVE
    )

    assert snapshot.can_accept_new_entries is True


def test_ready_runtime_cannot_process_market_data() -> None:
    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "PHOENIX-001"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.DRY_RUN,
        state=RuntimeState.READY,
        started_at=STARTED_AT,
        updated_at=UPDATED_AT,
    )

    assert (
        snapshot.can_process_market_data
        is False
    )

    assert (
        snapshot.can_accept_new_entries
        is False
    )


def test_recovering_runtime() -> None:
    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "PHOENIX-RECOVERY"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.RECOVERING,
        started_at=STARTED_AT,
        updated_at=UPDATED_AT,
        recovery_required=True,
    )

    assert snapshot.is_active is True

    assert (
        snapshot.can_process_market_data
        is False
    )

    assert (
        snapshot.can_accept_new_entries
        is False
    )


def test_recovering_requires_recovery_flag() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "RECOVERING runtime must have "
            "recovery_required=True"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-RECOVERY"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.RECOVERING,
            started_at=STARTED_AT,
            updated_at=UPDATED_AT,
            recovery_required=False,
        )


def test_recovered_runtime_cannot_require_recovery() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "recovered runtime cannot still "
            "require recovery"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-RECOVERY"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.RUNNING,
            started_at=STARTED_AT,
            updated_at=UPDATED_AT,
            recovery_required=True,
            recovered=True,
        )


def test_recovered_running_runtime() -> None:
    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "PHOENIX-RECOVERED"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.RUNNING,
        started_at=STARTED_AT,
        updated_at=UPDATED_AT,
        recovery_required=False,
        recovered=True,
    )

    assert snapshot.recovered is True

    assert (
        snapshot.can_accept_new_entries
        is True
    )


def test_created_runtime_cannot_be_recovered() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "CREATED runtime cannot be "
            "marked recovered"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-001"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.DRY_RUN,
            state=RuntimeState.CREATED,
            started_at=None,
            updated_at=UPDATED_AT,
            recovered=True,
        )


def test_stopped_runtime() -> None:
    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "PHOENIX-STOPPED"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.STOPPED,
        started_at=STARTED_AT,
        stopped_at=STOPPED_AT,
        updated_at=STOPPED_AT,
    )

    assert snapshot.is_terminal is True
    assert snapshot.is_active is False

    assert (
        snapshot.can_process_market_data
        is False
    )

    assert (
        snapshot.can_accept_new_entries
        is False
    )


def test_stopped_runtime_requires_stopped_at() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "STOPPED runtime requires "
            "stopped_at"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-STOPPED"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.STOPPED,
            started_at=STARTED_AT,
            updated_at=UPDATED_AT,
        )


def test_non_stopped_runtime_cannot_have_stopped_at() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "only STOPPED runtime may have "
            "stopped_at"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-001"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.RUNNING,
            started_at=STARTED_AT,
            updated_at=STOPPED_AT,
            stopped_at=STOPPED_AT,
        )


def test_stopped_time_cannot_precede_start() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "runtime stopped_at cannot be "
            "before started_at"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-001"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.STOPPED,
            started_at=STARTED_AT,
            stopped_at=(
                STARTED_AT
                - timedelta(seconds=1)
            ),
            updated_at=UPDATED_AT,
        )


def test_updated_time_cannot_precede_start() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "runtime updated_at cannot be "
            "before started_at"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-001"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.RUNNING,
            started_at=STARTED_AT,
            updated_at=(
                STARTED_AT
                - timedelta(seconds=1)
            ),
        )


def test_failed_runtime_requires_failure() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "FAILED runtime requires failure"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-FAILED"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.FAILED,
            started_at=STARTED_AT,
            updated_at=UPDATED_AT,
        )


def test_failed_runtime_snapshot() -> None:
    failure = RuntimeFailure(
        code=(
            RuntimeFailureCode
            .DATABASE_FAILED
        ),
        message="database unavailable",
        occurred_at=UPDATED_AT,
        recoverable=True,
        component="database",
    )

    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "PHOENIX-FAILED"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.FAILED,
        started_at=STARTED_AT,
        updated_at=UPDATED_AT,
        failure=failure,
        recovery_required=True,
    )

    assert snapshot.is_terminal is True
    assert snapshot.is_active is False

    assert snapshot.failure is failure

    assert (
        snapshot.can_accept_new_entries
        is False
    )


def test_failure_not_allowed_on_running_runtime() -> None:
    failure = RuntimeFailure(
        code=(
            RuntimeFailureCode
            .INTERNAL_ERROR
        ),
        message="unexpected runtime error",
        occurred_at=UPDATED_AT,
    )

    with pytest.raises(
        ValueError,
        match=(
            "runtime failure is only valid "
            "for FAILED state"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-001"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.RUNNING,
            started_at=STARTED_AT,
            updated_at=UPDATED_AT,
            failure=failure,
        )


def test_failure_cannot_occur_after_snapshot() -> None:
    failure = RuntimeFailure(
        code=(
            RuntimeFailureCode
            .INTERNAL_ERROR
        ),
        message="failure",
        occurred_at=(
            UPDATED_AT
            + timedelta(seconds=1)
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "runtime failure cannot occur "
            "after snapshot updated_at"
        ),
    ):
        RuntimeSnapshot(
            runtime_id=RuntimeId(
                "PHOENIX-FAILED"
            ),
            trading_date=TRADING_DATE,
            mode=RuntimeMode.LIVE,
            state=RuntimeState.FAILED,
            started_at=STARTED_AT,
            updated_at=UPDATED_AT,
            failure=failure,
        )


def test_stopping_runtime_is_active_but_blocks_entries() -> None:
    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "PHOENIX-STOPPING"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.STOPPING,
        started_at=STARTED_AT,
        updated_at=UPDATED_AT,
    )

    assert snapshot.is_active is True

    assert (
        snapshot.can_accept_new_entries
        is False
    )

    assert (
        snapshot.can_process_market_data
        is False
    )