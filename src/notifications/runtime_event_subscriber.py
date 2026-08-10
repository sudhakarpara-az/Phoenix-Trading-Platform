"""
Phoenix RuntimeEvent -> notification bridge.

This subscriber consumes the existing RuntimeEventBus. It does
not introduce another event bus and does not publish business
events itself.

Critical invariant:
    handle() must never raise.

RuntimeEventBus is part of Phoenix control flow. A broken
notification provider must therefore never turn a successful
trading/runtime transition into RuntimeEventDispatchError.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.logger import logger
from src.notifications.notification_dispatcher import (
    NotificationDispatcher,
)
from src.notifications.notification_deduplicator import (
    NotificationEventDeduplicator,
)
from src.notifications.payload_formatter import (
    NotificationPayloadFormatter,
)
from src.notifications.notification_types import (
    NotificationCategory,
    NotificationMessage,
    NotificationSeverity,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.runtime_events import (
    RuntimeEvent,
    RuntimeEventType,
)


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeEventNotificationRule:
    """
    Notification policy for one Phoenix runtime event type.
    """

    severity: NotificationSeverity
    category: NotificationCategory

    title: str
    body: str


class RuntimeEventNotificationSubscriber:
    """
    Converts operationally meaningful Phoenix events into
    channel-independent NotificationMessage values.

    High-frequency/noisy events are deliberately not subscribed:
        MARKET_TICK
        SIGNAL_CREATED
        OPTION_SELECTED
        ENTRY_ORDER_CREATED
        POSITION_UPDATED
        EXIT_ORDER_CREATED
        PNL_UPDATED
        RISK_UPDATED

    Those remain available to persistence/dashboard consumers.
    """

    _RULES: dict[
        RuntimeEventType,
        RuntimeEventNotificationRule,
    ] = {
        RuntimeEventType.RUNTIME_STARTED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.RUNTIME
                ),
                title="Phoenix runtime started",
                body=(
                    "Phoenix runtime startup has begun."
                ),
            ),

        RuntimeEventType.RUNTIME_READY:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.RUNTIME
                ),
                title="Phoenix runtime ready",
                body=(
                    "Phoenix runtime is ready for "
                    "trading-day execution."
                ),
            ),

        RuntimeEventType.RUNTIME_STOPPING:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.RUNTIME
                ),
                title="Phoenix runtime stopping",
                body=(
                    "Phoenix runtime shutdown has begun."
                ),
            ),

        RuntimeEventType.RUNTIME_FAILED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.CRITICAL
                ),
                category=(
                    NotificationCategory.RUNTIME
                ),
                title="Phoenix runtime failure",
                body=(
                    "Phoenix runtime entered FAILED state."
                ),
            ),

        RuntimeEventType.SIGNAL_REJECTED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.WARNING
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Trading signal rejected",
                body=(
                    "A Phoenix trading signal was rejected."
                ),
            ),

        RuntimeEventType.OPTION_SELECTION_FAILED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.WARNING
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Option selection failed",
                body=(
                    "Phoenix could not complete option "
                    "selection for a trading signal."
                ),
            ),

        RuntimeEventType.ENTRY_ORDER_SUBMITTED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Entry order submitted",
                body=(
                    "Phoenix submitted an entry order."
                ),
            ),

        RuntimeEventType.ENTRY_ORDER_FILLED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Entry order filled",
                body=(
                    "Phoenix entry order was filled."
                ),
            ),

        RuntimeEventType.ENTRY_ORDER_FAILED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.ERROR
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Entry order failed",
                body=(
                    "Phoenix entry-order processing failed."
                ),
            ),

        RuntimeEventType.POSITION_OPENED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Position opened",
                body=(
                    "Phoenix opened a managed position."
                ),
            ),

        RuntimeEventType.TARGET_TRIGGERED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.RISK
                ),
                title="Target triggered",
                body=(
                    "A Phoenix position target triggered."
                ),
            ),

        RuntimeEventType.STOP_LOSS_TRIGGERED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.WARNING
                ),
                category=(
                    NotificationCategory.RISK
                ),
                title="Stop-loss triggered",
                body=(
                    "A Phoenix position stop-loss triggered."
                ),
            ),

        RuntimeEventType.FORCE_EXIT_TRIGGERED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.WARNING
                ),
                category=(
                    NotificationCategory.RISK
                ),
                title="Force exit triggered",
                body=(
                    "Phoenix initiated force-exit processing."
                ),
            ),

        RuntimeEventType.EXIT_ORDER_SUBMITTED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Exit order submitted",
                body=(
                    "Phoenix submitted a position exit."
                ),
            ),

        RuntimeEventType.EXIT_ORDER_FILLED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Exit order filled",
                body=(
                    "Phoenix exit order was filled."
                ),
            ),

        RuntimeEventType.EXIT_ORDER_FAILED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.ERROR
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Exit order failed",
                body=(
                    "Phoenix exit-order processing failed."
                ),
            ),

        RuntimeEventType.POSITION_CLOSED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.TRADE
                ),
                title="Position closed",
                body=(
                    "Phoenix closed a managed position."
                ),
            ),

        RuntimeEventType.RECOVERY_STARTED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.WARNING
                ),
                category=(
                    NotificationCategory.RECOVERY
                ),
                title="Recovery started",
                body=(
                    "Phoenix is reconciling persisted "
                    "runtime state with broker truth."
                ),
            ),

        RuntimeEventType.RECOVERY_COMPLETED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.INFO
                ),
                category=(
                    NotificationCategory.RECOVERY
                ),
                title="Recovery completed",
                body=(
                    "Phoenix startup recovery completed "
                    "successfully."
                ),
            ),

        RuntimeEventType.RECOVERY_FAILED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.CRITICAL
                ),
                category=(
                    NotificationCategory.RECOVERY
                ),
                title="Recovery failed",
                body=(
                    "Phoenix could not safely reconcile "
                    "persisted state with broker truth."
                ),
            ),

        RuntimeEventType.HEALTH_CHANGED:
            RuntimeEventNotificationRule(
                severity=(
                    NotificationSeverity.WARNING
                ),
                category=(
                    NotificationCategory.HEALTH
                ),
                title="Runtime health changed",
                body=(
                    "Phoenix runtime or broker-account "
                    "health changed."
                ),
            ),
    }

    def __init__(
        self,
        *,
        dispatcher: NotificationDispatcher,
        deduplicator: NotificationEventDeduplicator | None = None,
        payload_formatter: NotificationPayloadFormatter | None = None,
    ) -> None:
        if not isinstance(
            dispatcher,
            NotificationDispatcher,
        ):
            raise TypeError(
                "dispatcher must be NotificationDispatcher"
            )

        self._dispatcher = dispatcher

        self._deduplicator = (
            deduplicator
            if deduplicator is not None
            else NotificationEventDeduplicator()
        )

        self._payload_formatter = (
            payload_formatter
            if payload_formatter is not None
            else NotificationPayloadFormatter()
        )

        self._duplicate_count = 0

        # Keep one stable callable identity so repeated subscribe()
        # calls remain idempotent with RuntimeEventBus.
        self._handler = self.handle

    @property
    def dispatcher(
        self,
    ) -> NotificationDispatcher:
        return self._dispatcher

    @property
    def deduplicator(
        self,
    ) -> NotificationEventDeduplicator:
        return self._deduplicator

    @property
    def payload_formatter(
        self,
    ) -> NotificationPayloadFormatter:
        return self._payload_formatter

    @property
    def duplicate_count(
        self,
    ) -> int:
        return self._duplicate_count

    @property
    def event_types(
        self,
    ) -> tuple[
        RuntimeEventType,
        ...,
    ]:
        return tuple(
            self._RULES
        )

    def subscribe(
        self,
        bus: RuntimeEventBus,
    ) -> tuple[
        RuntimeEventType,
        ...,
    ]:
        if not isinstance(
            bus,
            RuntimeEventBus,
        ):
            raise TypeError(
                "bus must be RuntimeEventBus"
            )

        added: list[
            RuntimeEventType
        ] = []

        for event_type in self.event_types:
            if bus.subscribe(
                event_type,
                self._handler,
            ):
                added.append(
                    event_type
                )

        return tuple(
            added
        )

    def handle(
        self,
        event: RuntimeEvent,
    ) -> None:
        """
        Handle one runtime event without propagating any
        notification failure into RuntimeEventBus.

        Duplicate identity is RuntimeEvent.event_id only.
        """

        claimed = False

        try:
            claimed = self._deduplicator.claim(
                event.event_id
            )

            if not claimed:
                self._duplicate_count += 1
                return

            message = self.message_for(
                event
            )

            if message is None:
                self._deduplicator.release(
                    event.event_id
                )
                return

            result = self._dispatcher.dispatch(
                message
            )

            # Queue/transport admission failure remains retryable.
            if not result.successful:
                self._deduplicator.release(
                    event.event_id
                )

        except Exception as exc:
            if claimed:
                try:
                    self._deduplicator.release(
                        event.event_id
                    )
                except Exception:
                    pass

            event_id = getattr(
                event,
                "event_id",
                "UNKNOWN",
            )

            logger.error(
                "notification subscriber isolated failure "
                f"event_id={event_id} "
                f"error={type(exc).__name__}: {exc}"
            )

    def message_for(
        self,
        event: RuntimeEvent,
    ) -> NotificationMessage | None:
        if not isinstance(
            event,
            RuntimeEvent,
        ):
            raise TypeError(
                "event must be RuntimeEvent"
            )

        rule = self._RULES.get(
            event.event_type
        )

        if rule is None:
            return None

        detail = self._payload_formatter.format(
            event.payload
        )

        body = rule.body

        if detail is not None:
            body = (
                f"{body}\n"
                f"Details: {detail}"
            )

        return NotificationMessage(
            notification_id=(
                f"NOTIFY:{event.event_id}"
            ),
            runtime_id=event.runtime_id,
            source_event_id=event.event_id,
            event_type=event.event_type,
            severity=rule.severity,
            category=rule.category,
            title=rule.title,
            body=body,
            occurred_at=event.occurred_at,
            correlation_id=(
                event.correlation_id
            ),
            causation_id=(
                event.causation_id
            ),
        )



__all__ = [
    "RuntimeEventNotificationRule",
    "RuntimeEventNotificationSubscriber",
]
