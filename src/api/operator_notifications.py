from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.notifications.daily_summary import (
    DailyOperationalSummarySnapshot,
)
from src.notifications.queued_channel import (
    NotificationQueueSnapshot,
)


class OperatorNotificationSummaryReader(
    Protocol,
):
    def snapshot(
        self,
        *,
        captured_at: datetime,
    ) -> DailyOperationalSummarySnapshot:
        ...


class OperatorNotificationQueueReader(
    Protocol,
):
    def snapshot(
        self,
        *,
        captured_at: datetime,
    ) -> NotificationQueueSnapshot:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorNotificationSummaryView:
    runtime_id: str

    total_count: int

    info_count: int
    warning_count: int
    error_count: int
    critical_count: int

    runtime_count: int
    trade_count: int
    risk_count: int
    recovery_count: int
    health_count: int
    summary_count: int

    first_event_at: datetime | None
    last_event_at: datetime | None

    captured_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorNotificationQueueView:
    started: bool
    accepting: bool

    capacity: int
    pending_count: int

    delivered_count: int
    failed_delivery_count: int
    dropped_count: int

    lifecycle_failure_count: int
    last_lifecycle_error: str | None

    captured_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorNotificationView:
    summary: OperatorNotificationSummaryView

    queue: OperatorNotificationQueueView | None

    captured_at: datetime


class OperatorNotificationService:
    """
    Passive M13 projection over exact retained M11 state.

    The service never dispatches notifications, mutates the queue,
    talks to Telegram, subscribes to events, or fabricates alert
    history.
    """

    def __init__(
        self,
        *,
        summary_collector:
            OperatorNotificationSummaryReader,
        queued_channel:
            OperatorNotificationQueueReader
            | None,
    ) -> None:
        self._summary_collector = (
            summary_collector
        )

        self._queued_channel = (
            queued_channel
        )

    @property
    def summary_collector(
        self,
    ) -> OperatorNotificationSummaryReader:
        return self._summary_collector

    @property
    def queued_channel(
        self,
    ) -> (
        OperatorNotificationQueueReader
        | None
    ):
        return self._queued_channel

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorNotificationView:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be datetime"
            )

        summary_snapshot = (
            self._summary_collector
            .snapshot(
                captured_at=captured_at,
            )
        )

        summary = (
            OperatorNotificationSummaryView(
                runtime_id=(
                    summary_snapshot
                    .runtime_id
                    .value
                ),
                total_count=(
                    summary_snapshot
                    .total_count
                ),
                info_count=(
                    summary_snapshot
                    .info_count
                ),
                warning_count=(
                    summary_snapshot
                    .warning_count
                ),
                error_count=(
                    summary_snapshot
                    .error_count
                ),
                critical_count=(
                    summary_snapshot
                    .critical_count
                ),
                runtime_count=(
                    summary_snapshot
                    .runtime_count
                ),
                trade_count=(
                    summary_snapshot
                    .trade_count
                ),
                risk_count=(
                    summary_snapshot
                    .risk_count
                ),
                recovery_count=(
                    summary_snapshot
                    .recovery_count
                ),
                health_count=(
                    summary_snapshot
                    .health_count
                ),
                summary_count=(
                    summary_snapshot
                    .summary_count
                ),
                first_event_at=(
                    summary_snapshot
                    .first_event_at
                ),
                last_event_at=(
                    summary_snapshot
                    .last_event_at
                ),
                captured_at=(
                    summary_snapshot
                    .captured_at
                ),
            )
        )

        queue_reader = (
            self._queued_channel
        )

        queue: (
            OperatorNotificationQueueView
            | None
        ) = None

        if queue_reader is not None:
            queue_snapshot = (
                queue_reader.snapshot(
                    captured_at=captured_at,
                )
            )

            queue = (
                OperatorNotificationQueueView(
                    started=(
                        queue_snapshot.started
                    ),
                    accepting=(
                        queue_snapshot.accepting
                    ),
                    capacity=(
                        queue_snapshot.capacity
                    ),
                    pending_count=(
                        queue_snapshot
                        .pending_count
                    ),
                    delivered_count=(
                        queue_snapshot
                        .delivered_count
                    ),
                    failed_delivery_count=(
                        queue_snapshot
                        .failed_delivery_count
                    ),
                    dropped_count=(
                        queue_snapshot
                        .dropped_count
                    ),
                    lifecycle_failure_count=(
                        queue_snapshot
                        .lifecycle_failure_count
                    ),
                    last_lifecycle_error=(
                        queue_snapshot
                        .last_lifecycle_error
                    ),
                    captured_at=(
                        queue_snapshot
                        .captured_at
                    ),
                )
            )

        return OperatorNotificationView(
            summary=summary,
            queue=queue,
            captured_at=captured_at,
        )


__all__ = [
    "OperatorNotificationQueueReader",
    "OperatorNotificationQueueView",
    "OperatorNotificationService",
    "OperatorNotificationSummaryReader",
    "OperatorNotificationSummaryView",
    "OperatorNotificationView",
]
