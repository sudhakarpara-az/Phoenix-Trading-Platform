"""
Phoenix notification and operational-alert boundaries.

M11 consumes Phoenix runtime/business events. Notification
delivery is deliberately isolated from trading correctness:
channel failures must never block execution, risk, recovery,
force exit, or runtime lifecycle transitions.
"""

from src.notifications.notification_channel import (
    NotificationChannel,
)
from src.notifications.notification_dispatcher import (
    NotificationDispatcher,
)
from src.notifications.notification_types import (
    NotificationCategory,
    NotificationDeliveryResult,
    NotificationDispatchResult,
    NotificationMessage,
    NotificationSeverity,
)
from src.notifications.daily_summary import (
    DailyOperationalSummaryCollector,
    DailyOperationalSummarySnapshot,
)
from src.notifications.end_of_day_notifications import (
    DailyOperationalSummaryDispatchService,
    DailySummaryDispatchResult,
    TradingDayEndOfDayEvaluator,
    TradingDayEndOfDayNotificationCoordinator,
    TradingDayEndOfDayNotificationResult,
)
from src.notifications.notification_deduplicator import (
    NotificationEventDeduplicator,
)
from src.notifications.payload_formatter import (
    NotificationPayloadFormatter,
)
from src.notifications.queued_channel import (
    NotificationQueueSnapshot,
    QueuedNotificationChannel,
)
from src.notifications.telegram_channel import (
    TelegramNotificationChannel,
    TelegramRequestSender,
)
from src.notifications.runtime_event_subscriber import (
    RuntimeEventNotificationRule,
    RuntimeEventNotificationSubscriber,
)

__all__ = [
    "NotificationCategory",
    "NotificationChannel",
    "NotificationDeliveryResult",
    "NotificationDispatcher",
    "NotificationDispatchResult",
    "NotificationMessage",
    "NotificationSeverity",
    "DailyOperationalSummaryCollector",
    "DailyOperationalSummarySnapshot",
    "DailyOperationalSummaryDispatchService",
    "DailySummaryDispatchResult",
    "NotificationEventDeduplicator",
    "NotificationPayloadFormatter",
    "NotificationQueueSnapshot",
    "QueuedNotificationChannel",
    "TelegramNotificationChannel",
    "TelegramRequestSender",
    "TradingDayEndOfDayEvaluator",
    "TradingDayEndOfDayNotificationCoordinator",
    "TradingDayEndOfDayNotificationResult",
    "RuntimeEventNotificationRule",
    "RuntimeEventNotificationSubscriber",
]
