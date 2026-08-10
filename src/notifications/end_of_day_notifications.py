"""
Phoenix M11 end-of-day notification integration.

This module wraps the established M10
TradingDayEndOfDayCoordinator boundary.

Critical invariants:

1. M10 remains authoritative for whether the trading day may
   transition from EXIT_ONLY to CLOSED.

2. Notification failure can never change the M10 EOD result.

3. An M10 EOD exception is re-raised after M11 makes a
   best-effort operational alert.

4. Daily summary delivery is idempotent by deterministic
   summary notification_id.

5. A failed summary delivery remains retryable on a later
   idempotent EOD evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol

from src.core.logger import logger
from src.notifications.daily_summary import (
    DailyOperationalSummaryCollector,
)
from src.notifications.notification_dispatcher import (
    NotificationDispatcher,
)
from src.notifications.notification_types import (
    NotificationCategory,
    NotificationDispatchResult,
    NotificationMessage,
    NotificationSeverity,
)
from src.notifications.queued_channel import (
    QueuedNotificationChannel,
)
from src.runtime.runtime_types import (
    RuntimeId,
)
from src.services.scheduler import (
    TradingDayEndOfDayResult,
)


class TradingDayEndOfDayEvaluator(
    Protocol,
):
    """
    Narrow M10 EOD evaluation boundary consumed by M11.
    """

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayEndOfDayResult:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class DailySummaryDispatchResult:
    """
    Result of one daily-summary delivery evaluation.
    """

    attempted: bool
    successful: bool
    already_dispatched: bool

    notification_id: str | None
    dispatch_result: NotificationDispatchResult | None
    error: str | None

    evaluated_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDayEndOfDayNotificationResult:
    """
    M10 EOD result plus optional M11 summary-delivery result.
    """

    end_of_day_result: TradingDayEndOfDayResult
    summary_result: DailySummaryDispatchResult | None


class DailyOperationalSummaryDispatchService:
    """
    Deliver the daily operational summary to outbound channels.

    The summary collector itself is deliberately NOT part of this
    dispatcher's channel list. Otherwise the summary would count
    itself as another daily operational event.
    """

    def __init__(
        self,
        *,
        collector: DailyOperationalSummaryCollector,
        dispatcher: NotificationDispatcher,
        queued_channel: QueuedNotificationChannel | None = None,
        enabled: bool = True,
    ) -> None:
        if not isinstance(
            collector,
            DailyOperationalSummaryCollector,
        ):
            raise TypeError(
                "collector must be "
                "DailyOperationalSummaryCollector"
            )

        if not isinstance(
            dispatcher,
            NotificationDispatcher,
        ):
            raise TypeError(
                "dispatcher must be NotificationDispatcher"
            )

        if type(enabled) is not bool:
            raise TypeError(
                "enabled must be bool"
            )

        if (
            queued_channel is not None
            and not isinstance(
                queued_channel,
                QueuedNotificationChannel,
            )
        ):
            raise TypeError(
                "queued_channel must be "
                "QueuedNotificationChannel or None"
            )

        self._collector = collector
        self._dispatcher = dispatcher
        self._queued_channel = queued_channel
        self._enabled = enabled

        self._successful_ids: set[str] = set()

        self._lock = RLock()

    @property
    def collector(
        self,
    ) -> DailyOperationalSummaryCollector:
        return self._collector

    @property
    def dispatcher(
        self,
    ) -> NotificationDispatcher:
        return self._dispatcher

    @property
    def enabled(
        self,
    ) -> bool:
        return self._enabled

    def dispatch(
        self,
        *,
        generated_at: datetime,
    ) -> DailySummaryDispatchResult:
        if type(generated_at) is not datetime:
            raise TypeError(
                "generated_at must be datetime"
            )

        notification_id: str | None = None

        try:
            message = self._collector.build_message(
                generated_at=generated_at
            )

            message = self._with_queue_snapshot(
                message=message,
                captured_at=generated_at,
            )

            notification_id = (
                message.notification_id
            )

            with self._lock:
                if (
                    notification_id
                    in self._successful_ids
                ):
                    return DailySummaryDispatchResult(
                        attempted=False,
                        successful=True,
                        already_dispatched=True,
                        notification_id=notification_id,
                        dispatch_result=None,
                        error=None,
                        evaluated_at=generated_at,
                    )

            if not self._enabled:
                return DailySummaryDispatchResult(
                    attempted=False,
                    successful=True,
                    already_dispatched=False,
                    notification_id=notification_id,
                    dispatch_result=None,
                    error=None,
                    evaluated_at=generated_at,
                )

            result = self._dispatcher.dispatch(
                message,
                dispatched_at=generated_at,
            )

            successful = (
                result.channel_count > 0
                and result.successful
            )

            error: str | None

            if successful:
                with self._lock:
                    self._successful_ids.add(
                        notification_id
                    )

                error = None

            else:
                error = (
                    "daily operational summary "
                    "delivery was not accepted "
                    "by all outbound channels"
                )

            return DailySummaryDispatchResult(
                attempted=True,
                successful=successful,
                already_dispatched=False,
                notification_id=notification_id,
                dispatch_result=result,
                error=error,
                evaluated_at=generated_at,
            )

        except Exception as exc:
            error = (
                f"{type(exc).__name__}: {exc}"
            )

            logger.error(
                "daily operational summary "
                f"dispatch isolated failure: {error}"
            )

            return DailySummaryDispatchResult(
                attempted=True,
                successful=False,
                already_dispatched=False,
                notification_id=notification_id,
                dispatch_result=None,
                error=error,
                evaluated_at=generated_at,
            )

    def _with_queue_snapshot(
        self,
        *,
        message: NotificationMessage,
        captured_at: datetime,
    ) -> NotificationMessage:
        queue = self._queued_channel

        if queue is None:
            return message

        snapshot = queue.snapshot(
            captured_at=captured_at
        )

        delivery_detail = (
            "Delivery queue ? "
            f"pending {snapshot.pending_count}, "
            f"delivered {snapshot.delivered_count}, "
            f"failed {snapshot.failed_delivery_count}, "
            f"dropped {snapshot.dropped_count}, "
            f"lifecycle failures "
            f"{snapshot.lifecycle_failure_count}"
        )

        return NotificationMessage(
            notification_id=(
                message.notification_id
            ),
            runtime_id=message.runtime_id,
            source_event_id=(
                message.source_event_id
            ),
            event_type=message.event_type,
            severity=message.severity,
            category=message.category,
            title=message.title,
            body=(
                f"{message.body}\n"
                f"{delivery_detail}"
            ),
            occurred_at=message.occurred_at,
            correlation_id=(
                message.correlation_id
            ),
            causation_id=(
                message.causation_id
            ),
        )


class TradingDayEndOfDayNotificationCoordinator:
    """
    M11 wrapper around the exact M10 EOD coordinator.

    M10 closure is evaluated first.

    Summary notification is attempted only after M10 reports
    complete=True.

    M10 exceptions are never swallowed or replaced.
    """

    def __init__(
        self,
        *,
        runtime_id: RuntimeId,
        end_of_day: TradingDayEndOfDayEvaluator,
        summary_service: DailyOperationalSummaryDispatchService,
        alert_dispatcher: NotificationDispatcher,
    ) -> None:
        if not isinstance(
            runtime_id,
            RuntimeId,
        ):
            raise TypeError(
                "runtime_id must be RuntimeId"
            )

        if not isinstance(
            summary_service,
            DailyOperationalSummaryDispatchService,
        ):
            raise TypeError(
                "summary_service must be "
                "DailyOperationalSummaryDispatchService"
            )

        if not isinstance(
            alert_dispatcher,
            NotificationDispatcher,
        ):
            raise TypeError(
                "alert_dispatcher must be "
                "NotificationDispatcher"
            )

        self._runtime_id = runtime_id
        self._end_of_day = end_of_day
        self._summary_service = summary_service
        self._alert_dispatcher = alert_dispatcher

    @property
    def runtime_id(
        self,
    ) -> RuntimeId:
        return self._runtime_id

    @property
    def summary_service(
        self,
    ) -> DailyOperationalSummaryDispatchService:
        return self._summary_service

    def evaluate(
        self,
        *,
        evaluated_at: datetime,
    ) -> TradingDayEndOfDayNotificationResult:
        if type(evaluated_at) is not datetime:
            raise TypeError(
                "evaluated_at must be datetime"
            )

        try:
            result = self._end_of_day.evaluate(
                evaluated_at=evaluated_at
            )

        except Exception as exc:
            self._alert_eod_failure(
                evaluated_at=evaluated_at,
                error=exc,
            )

            raise

        summary_result: DailySummaryDispatchResult | None = None

        if result.complete:
            summary_result = (
                self._summary_service.dispatch(
                    generated_at=evaluated_at
                )
            )

        return TradingDayEndOfDayNotificationResult(
            end_of_day_result=result,
            summary_result=summary_result,
        )

    def _alert_eod_failure(
        self,
        *,
        evaluated_at: datetime,
        error: Exception,
    ) -> None:
        """
        Best-effort alert only.

        Alert failure never masks the original M10 exception.
        """

        try:
            error_text = (
                f"{type(error).__name__}: "
                f"{error}"
            )

            source_id = (
                "EOD-FAILURE:"
                f"{self._runtime_id.value}:"
                f"{evaluated_at.isoformat()}"
            )

            message = NotificationMessage(
                notification_id=(
                    f"NOTIFY:{source_id}"
                ),
                runtime_id=self._runtime_id,
                source_event_id=source_id,
                event_type=None,
                severity=(
                    NotificationSeverity.ERROR
                ),
                category=(
                    NotificationCategory.RUNTIME
                ),
                title=(
                    "Trading-day close evaluation failed"
                ),
                body=error_text[:1000],
                occurred_at=evaluated_at,
            )

            self._alert_dispatcher.dispatch(
                message,
                dispatched_at=evaluated_at,
            )

        except Exception as alert_exc:
            logger.error(
                "EOD failure alert isolated failure "
                f"error={type(alert_exc).__name__}: "
                f"{alert_exc}"
            )


__all__ = [
    "DailyOperationalSummaryDispatchService",
    "DailySummaryDispatchResult",
    "TradingDayEndOfDayEvaluator",
    "TradingDayEndOfDayNotificationCoordinator",
    "TradingDayEndOfDayNotificationResult",
]
