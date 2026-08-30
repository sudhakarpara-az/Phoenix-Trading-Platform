from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Protocol

from src.services.scheduler import (
    TradingDaySnapshot,
)


class OperatorSchedulerSnapshotReader(
    Protocol,
):
    @property
    def snapshot(
        self,
    ) -> TradingDaySnapshot:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorSchedulerView:
    trading_date: date

    state: str

    updated_at: datetime

    started_at: datetime | None
    closed_at: datetime | None

    failure_message: str | None

    is_terminal: bool

    can_accept_new_entries: bool
    can_manage_positions: bool

    captured_at: datetime


class OperatorSchedulerService:
    """
    Passive M13 projection of the exact retained M10
    TradingDayScheduler state.

    This service:

        - reads the existing scheduler snapshot;
        - performs no scheduler transition;
        - performs no market-time calculation;
        - performs no strategy calculation;
        - performs no broker call;
        - performs no persistence write.
    """

    def __init__(
        self,
        *,
        scheduler: OperatorSchedulerSnapshotReader,
    ) -> None:
        self._scheduler = scheduler

    @property
    def scheduler(
        self,
    ) -> OperatorSchedulerSnapshotReader:
        return self._scheduler

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorSchedulerView:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be a datetime"
            )

        snapshot = (
            self._scheduler.snapshot
        )

        return OperatorSchedulerView(
            trading_date=(
                snapshot.trading_date
            ),
            state=(
                snapshot.state.value
            ),
            updated_at=(
                snapshot.updated_at
            ),
            started_at=(
                snapshot.started_at
            ),
            closed_at=(
                snapshot.closed_at
            ),
            failure_message=(
                snapshot.failure_message
            ),
            is_terminal=(
                snapshot.is_terminal
            ),
            can_accept_new_entries=(
                snapshot
                .can_accept_new_entries
            ),
            can_manage_positions=(
                snapshot
                .can_manage_positions
            ),
            captured_at=captured_at,
        )


__all__ = [
    "OperatorSchedulerService",
    "OperatorSchedulerSnapshotReader",
    "OperatorSchedulerView",
]
