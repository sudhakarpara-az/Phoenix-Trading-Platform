from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    date,
    datetime,
)

import pytest

from src.api.operator_snapshot import (
    OperatorSnapshotService,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
    RuntimeSnapshot,
    RuntimeState,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

CREATED = datetime(
    2026,
    8,
    10,
    9,
    0,
)

STARTED = datetime(
    2026,
    8,
    10,
    9,
    15,
)

UPDATED = datetime(
    2026,
    8,
    10,
    10,
    30,
)

CAPTURED = datetime(
    2026,
    8,
    10,
    10,
    31,
)


def make_runtime_snapshot(
) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        runtime_id=RuntimeId(
            "M13-RUNTIME-001"
        ),
        trading_date=TRADING_DATE,
        mode=RuntimeMode.DRY_RUN,
        state=RuntimeState.RUNNING,
        started_at=STARTED,
        updated_at=UPDATED,
        stopped_at=None,
        failure=None,
        recovery_required=False,
        recovered=False,
    )


class FakeRuntimeReader:
    def __init__(
        self,
        snapshot: RuntimeSnapshot,
    ) -> None:
        self._snapshot = snapshot
        self.read_count = 0

    @property
    def snapshot(
        self,
    ) -> RuntimeSnapshot:
        self.read_count += 1
        return self._snapshot


@dataclass(
    frozen=True,
    slots=True,
)
class FakePosition:
    open_quantity: int
    realized_pnl: float


class FakePositionReader:
    def __init__(
        self,
        positions: tuple[
            FakePosition,
            ...,
        ],
    ) -> None:
        self._positions = positions
        self.read_count = 0

    def all(
        self,
    ) -> tuple[
        FakePosition,
        ...,
    ]:
        self.read_count += 1
        return self._positions


def test_empty_operator_snapshot():
    runtime = FakeRuntimeReader(
        make_runtime_snapshot()
    )

    positions = FakePositionReader(
        ()
    )

    snapshot = OperatorSnapshotService(
        runtime=runtime,
        positions=positions,
    ).capture(
        captured_at=CAPTURED
    )

    assert (
        snapshot.runtime.runtime_id
        == "M13-RUNTIME-001"
    )

    assert (
        snapshot.runtime.trading_date
        == TRADING_DATE
    )

    assert snapshot.runtime.mode == "DRY_RUN"
    assert snapshot.runtime.state == "RUNNING"

    assert (
        snapshot.runtime.started_at
        == STARTED
    )

    assert (
        snapshot.runtime.updated_at
        == UPDATED
    )

    assert snapshot.runtime.stopped_at is None
    assert snapshot.runtime.recovery_required is False
    assert snapshot.runtime.recovered is False
    assert snapshot.runtime.has_failure is False

    assert (
        snapshot.positions.tracked_position_count
        == 0
    )

    assert (
        snapshot.positions.open_position_count
        == 0
    )

    assert snapshot.positions.open_quantity == 0
    assert snapshot.positions.realized_pnl == 0.0

    assert snapshot.captured_at == CAPTURED


def test_position_summary_is_aggregated_without_mutation():
    runtime = FakeRuntimeReader(
        make_runtime_snapshot()
    )

    positions = FakePositionReader(
        (
            FakePosition(
                open_quantity=65,
                realized_pnl=0.0,
            ),
            FakePosition(
                open_quantity=0,
                realized_pnl=325.0,
            ),
            FakePosition(
                open_quantity=20,
                realized_pnl=-100.0,
            ),
        )
    )

    snapshot = OperatorSnapshotService(
        runtime=runtime,
        positions=positions,
    ).capture(
        captured_at=CAPTURED
    )

    assert (
        snapshot.positions.tracked_position_count
        == 3
    )

    assert (
        snapshot.positions.open_position_count
        == 2
    )

    assert snapshot.positions.open_quantity == 85

    assert (
        snapshot.positions.realized_pnl
        == 225.0
    )


def test_each_authoritative_source_is_read_once():
    runtime = FakeRuntimeReader(
        make_runtime_snapshot()
    )

    positions = FakePositionReader(
        (
            FakePosition(
                open_quantity=65,
                realized_pnl=0.0,
            ),
        )
    )

    service = OperatorSnapshotService(
        runtime=runtime,
        positions=positions,
    )

    service.capture(
        captured_at=CAPTURED
    )

    assert runtime.read_count == 1
    assert positions.read_count == 1


def test_invalid_capture_time_rejected():
    service = OperatorSnapshotService(
        runtime=FakeRuntimeReader(
            make_runtime_snapshot()
        ),
        positions=FakePositionReader(
            ()
        ),
    )

    with pytest.raises(
        TypeError,
        match="captured_at must be datetime",
    ):
        service.capture(
            captured_at=TRADING_DATE  # type: ignore[arg-type]
        )
