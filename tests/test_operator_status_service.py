from __future__ import annotations

from datetime import date
from datetime import datetime

import pytest

from src.api.api_types import (
    OperatorPositionSummary,
    OperatorRuntimeView,
    OperatorSnapshot,
)
from src.api.operator_account import (
    OperatorAccountView,
)
from src.api.operator_status import (
    OperatorStatusService,
    OperatorStatusView,
)
from src.app.trading_control import (
    TradingControlSnapshot,
    TradingControlState,
)


NOW = datetime(
    2026,
    8,
    10,
    14,
    45,
)


def make_snapshot() -> OperatorSnapshot:
    return OperatorSnapshot(
        runtime=OperatorRuntimeView(
            runtime_id="runtime-1",
            trading_date=date(
                2026,
                8,
                10,
            ),
            mode="LIVE",
            state="RUNNING",
            started_at=NOW,
            updated_at=NOW,
            stopped_at=None,
            recovery_required=False,
            recovered=True,
            has_failure=False,
        ),
        positions=(
            OperatorPositionSummary(
                tracked_position_count=1,
                open_position_count=1,
                open_quantity=65,
                realized_pnl=0.0,
            )
        ),
        captured_at=NOW,
    )


def make_account(
    *,
    broker: str = "DHAN",
    account_id: str = "ACCOUNT-1",
) -> OperatorAccountView:
    return OperatorAccountView(
        broker=broker,
        account_id=account_id,
        profile=None,
        session=None,
        funds=None,
        connectivity=None,
        health=None,
        eligibility=None,
        captured_at=NOW,
    )


class FakeSnapshotService:
    def __init__(
        self,
    ) -> None:
        self.calls = 0
        self.captured_at: (
            datetime | None
        ) = None

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorSnapshot:
        self.calls += 1
        self.captured_at = captured_at

        return make_snapshot()


class FakeAccountService:
    def __init__(
        self,
        *,
        broker: str = "DHAN",
        account_id: str = "ACCOUNT-1",
    ) -> None:
        self.calls = 0
        self.captured_at: (
            datetime | None
        ) = None

        self.broker = broker
        self.account_id = account_id

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorAccountView:
        self.calls += 1
        self.captured_at = captured_at

        return make_account(
            broker=self.broker,
            account_id=self.account_id,
        )


class FakeControl:
    def __init__(
        self,
        *,
        broker: str = "DHAN",
        account_id: str = "ACCOUNT-1",
        state: TradingControlState = (
            TradingControlState.ACTIVE
        ),
    ) -> None:
        self._broker = broker
        self._account_id = account_id
        self._state = state

        self.snapshot_reads = 0

    @property
    def snapshot(
        self,
    ) -> TradingControlSnapshot:
        self.snapshot_reads += 1

        return TradingControlSnapshot(
            broker=self._broker,
            account_id=self._account_id,
            state=self._state,
            changed_at=NOW,
            message=None,
        )


def make_service(
    *,
    account_broker: str = "DHAN",
    account_id: str = "ACCOUNT-1",
    control_broker: str = "DHAN",
    control_account_id: str = "ACCOUNT-1",
    control_state: TradingControlState = (
        TradingControlState.ACTIVE
    ),
):
    snapshot = FakeSnapshotService()

    account = FakeAccountService(
        broker=account_broker,
        account_id=account_id,
    )

    control = FakeControl(
        broker=control_broker,
        account_id=control_account_id,
        state=control_state,
    )

    service = OperatorStatusService(
        snapshot=snapshot,
        account=account,
        control=control,
    )

    return (
        service,
        snapshot,
        account,
        control,
    )


def test_constructor_preserves_exact_dependencies() -> None:
    (
        service,
        snapshot,
        account,
        control,
    ) = make_service()

    assert service.snapshot is snapshot
    assert service.account is account
    assert service.control is control


def test_capture_reads_each_owner_once_with_same_timestamp() -> None:
    (
        service,
        snapshot,
        account,
        control,
    ) = make_service()

    result = service.capture(
        captured_at=NOW
    )

    assert isinstance(
        result,
        OperatorStatusView,
    )

    assert snapshot.calls == 1
    assert account.calls == 1
    assert control.snapshot_reads == 1

    assert snapshot.captured_at == NOW
    assert account.captured_at == NOW

    assert result.captured_at == NOW

    assert (
        result.snapshot.runtime.runtime_id
        == "runtime-1"
    )

    assert result.account.broker == "DHAN"

    assert result.control.state == "ACTIVE"

    assert (
        result.control.new_entries_allowed
        is True
    )


def test_exit_and_stop_control_is_projected_fail_closed() -> None:
    (
        service,
        _,
        _,
        _,
    ) = make_service(
        control_state=(
            TradingControlState
            .EXIT_AND_STOP
        )
    )

    result = service.capture(
        captured_at=NOW
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


def test_broker_identity_mismatch_is_rejected() -> None:
    (
        service,
        _,
        _,
        _,
    ) = make_service(
        account_broker="DHAN",
        control_broker="OTHER",
    )

    with pytest.raises(
        ValueError,
        match=(
            "broker identity mismatch"
        ),
    ):
        service.capture(
            captured_at=NOW
        )


def test_account_identity_mismatch_is_rejected() -> None:
    (
        service,
        _,
        _,
        _,
    ) = make_service(
        account_id="ACCOUNT-1",
        control_account_id="ACCOUNT-2",
    )

    with pytest.raises(
        ValueError,
        match=(
            "account identity mismatch"
        ),
    ):
        service.capture(
            captured_at=NOW
        )


def test_invalid_capture_time_rejected_before_reads() -> None:
    (
        service,
        snapshot,
        account,
        control,
    ) = make_service()

    with pytest.raises(
        TypeError,
        match="captured_at must be datetime",
    ):
        service.capture(
            captured_at="invalid",  # type: ignore[arg-type]
        )

    assert snapshot.calls == 0
    assert account.calls == 0
    assert control.snapshot_reads == 0
