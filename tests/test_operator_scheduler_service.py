from __future__ import annotations

from datetime import date
from datetime import datetime

import pytest

from src.api.operator_scheduler import (
    OperatorSchedulerService,
)
from src.services.scheduler import (
    TradingDaySnapshot,
    TradingDayState,
)


TRADING_DATE = date(
    2026,
    8,
    31,
)

STARTED_AT = datetime(
    2026,
    8,
    31,
    9,
    0,
)

UPDATED_AT = datetime(
    2026,
    8,
    31,
    9,
    20,
)

CAPTURED_AT = datetime(
    2026,
    8,
    31,
    9,
    20,
    1,
)


class FakeScheduler:
    def __init__(
        self,
        *,
        snapshot: TradingDaySnapshot,
    ) -> None:
        self._snapshot = snapshot

        self.snapshot_reads = 0

    @property
    def snapshot(
        self,
    ) -> TradingDaySnapshot:
        self.snapshot_reads += 1

        return self._snapshot


def test_scheduler_projection_preserves_exact_reader() -> None:
    scheduler = FakeScheduler(
        snapshot=TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=(
                TradingDayState.MONITORING
            ),
            updated_at=UPDATED_AT,
            started_at=STARTED_AT,
        )
    )

    service = OperatorSchedulerService(
        scheduler=scheduler,
    )

    assert (
        service.scheduler
        is scheduler
    )


def test_scheduler_projection_maps_exact_snapshot_once() -> None:
    scheduler = FakeScheduler(
        snapshot=TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=(
                TradingDayState.MONITORING
            ),
            updated_at=UPDATED_AT,
            started_at=STARTED_AT,
        )
    )

    service = OperatorSchedulerService(
        scheduler=scheduler,
    )

    result = service.capture(
        captured_at=CAPTURED_AT,
    )

    assert scheduler.snapshot_reads == 1

    assert (
        result.trading_date
        == TRADING_DATE
    )

    assert (
        result.state
        == "MONITORING"
    )

    assert (
        result.updated_at
        == UPDATED_AT
    )

    assert (
        result.started_at
        == STARTED_AT
    )

    assert result.closed_at is None

    assert (
        result.failure_message
        is None
    )

    assert (
        result.is_terminal
        is False
    )

    assert (
        result.can_accept_new_entries
        is True
    )

    assert (
        result.can_manage_positions
        is True
    )

    assert (
        result.captured_at
        == CAPTURED_AT
    )


def test_scheduler_projection_maps_failed_state() -> None:
    failed_at = datetime(
        2026,
        8,
        31,
        10,
        5,
    )

    scheduler = FakeScheduler(
        snapshot=TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=(
                TradingDayState.FAILED
            ),
            updated_at=failed_at,
            started_at=STARTED_AT,
            failure_message=(
                "scheduler failure"
            ),
        )
    )

    service = OperatorSchedulerService(
        scheduler=scheduler,
    )

    result = service.capture(
        captured_at=failed_at,
    )

    assert (
        result.state
        == "FAILED"
    )

    assert (
        result.failure_message
        == "scheduler failure"
    )

    assert (
        result.is_terminal
        is True
    )

    assert (
        result.can_accept_new_entries
        is False
    )

    assert (
        result.can_manage_positions
        is False
    )


def test_scheduler_projection_rejects_non_datetime_capture() -> None:
    scheduler = FakeScheduler(
        snapshot=TradingDaySnapshot(
            trading_date=TRADING_DATE,
            state=(
                TradingDayState.MONITORING
            ),
            updated_at=UPDATED_AT,
            started_at=STARTED_AT,
        )
    )

    service = OperatorSchedulerService(
        scheduler=scheduler,
    )

    with pytest.raises(
        TypeError,
        match=(
            "captured_at must be "
            "a datetime"
        ),
    ):
        service.capture(
            captured_at=object(),  # type: ignore[arg-type]
        )

    assert scheduler.snapshot_reads == 0
