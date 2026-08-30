from __future__ import annotations

from datetime import date, datetime

import pytest

from src.app.trading_control import (
    TradingControlRecordData,
    TradingControlService,
    TradingControlState,
)
from src.risk.daily_risk_manager import (
    DailyRiskManager,
)
from src.risk.position_registry import (
    PositionRegistry,
)


NOW = datetime(
    2026,
    8,
    10,
    12,
    0,
)

LATER = datetime(
    2026,
    8,
    10,
    12,
    5,
)

TODAY = date(
    2026,
    8,
    10,
)




class FakeRepository:
    def __init__(
        self,
        record: TradingControlRecordData | None = None,
        log: list[str] | None = None,
    ) -> None:
        self.record = record
        self.log = (
            log
            if log is not None
            else []
        )

    def get_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> TradingControlRecordData | None:
        self.log.append(
            "get"
        )

        return self.record

    def set_for_account(
        self,
        *,
        broker: str,
        account_id: str,
        state: str,
        message: str | None,
        changed_at: datetime,
    ) -> TradingControlRecordData:
        self.log.append(
            f"persist:{state}"
        )

        self.record = TradingControlRecordData(
            broker=broker,
            account_id=account_id,
            state=state,
            changed_at=changed_at,
            message=message,
        )

        return self.record


class FakeManualLock:
    def __init__(
        self,
        log: list[str],
    ) -> None:
        self.log = log
        self.locked = False

    def set_manual_lock(
        self,
        *,
        message: str | None = None,
    ) -> None:
        self.log.append(
            "lock"
        )
        self.locked = True

    def clear_manual_lock(
        self,
    ) -> None:
        self.log.append(
            "clear"
        )
        self.locked = False

    def is_manually_locked(
        self,
    ) -> bool:
        return self.locked


def test_unrestored_control_fails_closed():
    repo = FakeRepository()
    lock = FakeManualLock([])

    service = TradingControlService(
        broker="DHAN",
        account_id="A1",
        repository=repo,
        manual_entry_lock=lock,
    )

    assert (
        service.can_accept_new_entries()
        is False
    )


def test_missing_record_restores_active():
    repo = FakeRepository()
    lock = FakeManualLock([])

    service = TradingControlService(
        broker="DHAN",
        account_id="A1",
        repository=repo,
        manual_entry_lock=lock,
    )

    snapshot = service.restore()

    assert (
        snapshot.state
        is TradingControlState.ACTIVE
    )

    assert (
        service.can_accept_new_entries()
        is True
    )

    assert lock.locked is False


def test_restart_restores_exit_and_stop_lock():
    repo = FakeRepository(
        TradingControlRecordData(
            broker="DHAN",
            account_id="A1",
            state="EXIT_AND_STOP",
            changed_at=NOW,
            message="operator stop",
        )
    )

    log: list[str] = []

    lock = FakeManualLock(
        log
    )

    service = TradingControlService(
        broker="DHAN",
        account_id="A1",
        repository=repo,
        manual_entry_lock=lock,
    )

    snapshot = service.restore()

    assert (
        snapshot.state
        is TradingControlState.EXIT_AND_STOP
    )

    assert lock.locked is True

    assert (
        service.can_accept_new_entries()
        is False
    )

    assert log == [
        "lock",
    ]


def test_stop_persists_before_entry_lock():
    log: list[str] = []

    repo = FakeRepository(
        log=log
    )

    lock = FakeManualLock(
        log
    )

    service = TradingControlService(
        broker="DHAN",
        account_id="A1",
        repository=repo,
        manual_entry_lock=lock,
    )

    service.restore()

    log.clear()

    service.activate_exit_and_stop(
        changed_at=NOW,
        message="manual stop",
    )

    assert log == [
        "persist:EXIT_AND_STOP",
        "lock",
    ]


def test_resume_persists_before_unlock():
    log: list[str] = []

    repo = FakeRepository(
        TradingControlRecordData(
            broker="DHAN",
            account_id="A1",
            state="EXIT_AND_STOP",
            changed_at=NOW,
        ),
        log=log,
    )

    lock = FakeManualLock(
        log
    )

    service = TradingControlService(
        broker="DHAN",
        account_id="A1",
        repository=repo,
        manual_entry_lock=lock,
    )

    service.restore()

    log.clear()

    snapshot = service.resume(
        changed_at=LATER
    )

    assert (
        snapshot.state
        is TradingControlState.ACTIVE
    )

    assert log == [
        "persist:ACTIVE",
        "clear",
    ]


def test_actual_daily_risk_manager_blocks_entries():
    repo = FakeRepository()

    manager = DailyRiskManager(
        registry=PositionRegistry()
    )

    service = TradingControlService(
        broker="DHAN",
        account_id="A1",
        repository=repo,
        manual_entry_lock=manager,
    )

    service.restore()

    before = manager.build_snapshot(
        trading_date=TODAY,
        position_pnls={},
        captured_at=NOW,
    )

    assert (
        before.new_entries_allowed
        is True
    )

    service.activate_exit_and_stop(
        changed_at=NOW
    )

    stopped = manager.build_snapshot(
        trading_date=TODAY,
        position_pnls={},
        captured_at=LATER,
    )

    assert (
        stopped.new_entries_allowed
        is False
    )

    service.resume(
        changed_at=LATER
    )

    resumed = manager.build_snapshot(
        trading_date=TODAY,
        position_pnls={},
        captured_at=LATER,
    )

    assert (
        resumed.new_entries_allowed
        is True
    )


def test_invalid_timestamp_does_not_persist():
    log: list[str] = []

    repo = FakeRepository(
        log=log
    )

    lock = FakeManualLock(
        log
    )

    service = TradingControlService(
        broker="DHAN",
        account_id="A1",
        repository=repo,
        manual_entry_lock=lock,
    )

    service.restore()

    log.clear()

    with pytest.raises(
        TypeError,
        match="changed_at must be datetime",
    ):
        service.activate_exit_and_stop(
            changed_at=None,  # type: ignore[arg-type]
        )

    assert log == []
