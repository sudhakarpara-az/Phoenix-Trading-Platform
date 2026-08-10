"""
Phoenix daily operational notification summary.

The collector is an in-process NotificationChannel. It receives
the same already-filtered NotificationMessage values delivered
through the M11 notification dispatcher.

It does not:
    - introduce another RuntimeEventBus,
    - interpret broker responses,
    - modify trading state,
    - affect execution/risk/recovery control flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from src.notifications.notification_types import (
    NotificationCategory,
    NotificationDeliveryResult,
    NotificationMessage,
    NotificationSeverity,
)
from src.runtime.runtime_types import (
    RuntimeId,
)


@dataclass(
    frozen=True,
    slots=True,
)
class DailyOperationalSummarySnapshot:
    """
    Immutable daily operational counters.
    """

    runtime_id: RuntimeId

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


class DailyOperationalSummaryCollector:
    """
    Thread-safe in-memory operational summary collector.

    notification_id provides idempotency so a notification retry
    cannot inflate daily summary counters.
    """

    def __init__(
        self,
        *,
        runtime_id: RuntimeId,
        capacity: int = 10000,
    ) -> None:
        if not isinstance(
            runtime_id,
            RuntimeId,
        ):
            raise TypeError(
                "runtime_id must be RuntimeId"
            )

        if (
            type(capacity) is not int
            or capacity <= 0
        ):
            raise ValueError(
                "capacity must be a positive integer"
            )

        self._runtime_id = runtime_id
        self._capacity = capacity

        self._lock = RLock()

        self._notification_ids: set[str] = set()

        self._notification_order: list[str] = []

        self._severity_counts = {
            severity: 0
            for severity in NotificationSeverity
        }

        self._category_counts = {
            category: 0
            for category in NotificationCategory
        }

        self._total_count = 0

        self._first_event_at: datetime | None = None

        self._last_event_at: datetime | None = None

    @property
    def name(
        self,
    ) -> str:
        return "DAILY_SUMMARY_COLLECTOR"

    @property
    def runtime_id(
        self,
    ) -> RuntimeId:
        return self._runtime_id

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        if not isinstance(
            message,
            NotificationMessage,
        ):
            raise TypeError(
                "message must be NotificationMessage"
            )

        attempted_at = datetime.now()

        with self._lock:
            if (
                message.notification_id
                in self._notification_ids
            ):
                return NotificationDeliveryResult(
                    channel=self.name,
                    success=True,
                    attempted_at=attempted_at,
                )

            self._notification_ids.add(
                message.notification_id
            )

            self._notification_order.append(
                message.notification_id
            )

            while (
                len(
                    self._notification_order
                )
                > self._capacity
            ):
                oldest = self._notification_order.pop(
                    0
                )

                self._notification_ids.discard(
                    oldest
                )

            self._total_count += 1

            self._severity_counts[
                message.severity
            ] += 1

            self._category_counts[
                message.category
            ] += 1

            if (
                self._first_event_at is None
                or message.occurred_at
                < self._first_event_at
            ):
                self._first_event_at = (
                    message.occurred_at
                )

            if (
                self._last_event_at is None
                or message.occurred_at
                > self._last_event_at
            ):
                self._last_event_at = (
                    message.occurred_at
                )

        return NotificationDeliveryResult(
            channel=self.name,
            success=True,
            attempted_at=attempted_at,
        )

    def snapshot(
        self,
        *,
        captured_at: datetime,
    ) -> DailyOperationalSummarySnapshot:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be datetime"
            )

        with self._lock:
            return DailyOperationalSummarySnapshot(
                runtime_id=self._runtime_id,
                total_count=self._total_count,
                info_count=(
                    self._severity_counts[
                        NotificationSeverity.INFO
                    ]
                ),
                warning_count=(
                    self._severity_counts[
                        NotificationSeverity.WARNING
                    ]
                ),
                error_count=(
                    self._severity_counts[
                        NotificationSeverity.ERROR
                    ]
                ),
                critical_count=(
                    self._severity_counts[
                        NotificationSeverity.CRITICAL
                    ]
                ),
                runtime_count=(
                    self._category_counts[
                        NotificationCategory.RUNTIME
                    ]
                ),
                trade_count=(
                    self._category_counts[
                        NotificationCategory.TRADE
                    ]
                ),
                risk_count=(
                    self._category_counts[
                        NotificationCategory.RISK
                    ]
                ),
                recovery_count=(
                    self._category_counts[
                        NotificationCategory.RECOVERY
                    ]
                ),
                health_count=(
                    self._category_counts[
                        NotificationCategory.HEALTH
                    ]
                ),
                summary_count=(
                    self._category_counts[
                        NotificationCategory.SUMMARY
                    ]
                ),
                first_event_at=(
                    self._first_event_at
                ),
                last_event_at=(
                    self._last_event_at
                ),
                captured_at=captured_at,
            )

    def build_message(
        self,
        *,
        generated_at: datetime,
    ) -> NotificationMessage:
        if type(generated_at) is not datetime:
            raise TypeError(
                "generated_at must be datetime"
            )

        snapshot = self.snapshot(
            captured_at=generated_at
        )

        severity = NotificationSeverity.INFO

        if snapshot.critical_count > 0:
            severity = (
                NotificationSeverity.CRITICAL
            )

        elif snapshot.error_count > 0:
            severity = (
                NotificationSeverity.ERROR
            )

        elif snapshot.warning_count > 0:
            severity = (
                NotificationSeverity.WARNING
            )

        source_id = (
            "DAILY-SUMMARY:"
            f"{self._runtime_id.value}:"
            f"{generated_at.date().isoformat()}"
        )

        body = "\n".join(
            (
                (
                    "Operational alerts: "
                    f"{snapshot.total_count}"
                ),
                (
                    "Severity ? "
                    f"INFO {snapshot.info_count}, "
                    f"WARNING {snapshot.warning_count}, "
                    f"ERROR {snapshot.error_count}, "
                    f"CRITICAL {snapshot.critical_count}"
                ),
                (
                    "Categories ? "
                    f"Runtime {snapshot.runtime_count}, "
                    f"Trade {snapshot.trade_count}, "
                    f"Risk {snapshot.risk_count}, "
                    f"Recovery {snapshot.recovery_count}, "
                    f"Health {snapshot.health_count}"
                ),
                (
                    "Delivery summary generated at "
                    f"{generated_at.isoformat()}."
                ),
            )
        )

        return NotificationMessage(
            notification_id=(
                f"NOTIFY:{source_id}"
            ),
            runtime_id=self._runtime_id,
            source_event_id=source_id,
            event_type=None,
            severity=severity,
            category=(
                NotificationCategory.SUMMARY
            ),
            title=(
                "Phoenix daily operational summary"
            ),
            body=body,
            occurred_at=generated_at,
        )


__all__ = [
    "DailyOperationalSummaryCollector",
    "DailyOperationalSummarySnapshot",
]
