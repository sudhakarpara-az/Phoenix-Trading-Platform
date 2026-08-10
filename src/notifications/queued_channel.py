"""
Bounded asynchronous Phoenix notification delivery.

RuntimeEventBus subscribers must remain fast and deterministic.
Network I/O therefore occurs only on this worker thread.

Notification infrastructure is observability, not a trading
correctness dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from queue import (
    Empty,
    Full,
    Queue,
)
from threading import (
    Event,
    RLock,
    Thread,
    current_thread,
)

from src.core.logger import logger
from src.notifications.notification_channel import (
    NotificationChannel,
)
from src.notifications.notification_types import (
    NotificationDeliveryResult,
    NotificationMessage,
)


@dataclass(
    frozen=True,
    slots=True,
)
class NotificationQueueSnapshot:
    """
    Immutable operational health view of the async queue.
    """

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


class QueuedNotificationChannel:
    """
    Bounded non-blocking wrapper around one notification channel.

    RuntimeEventBus path:
        send()
            ->
        Queue.put_nowait()

    Worker path:
        queue
            ->
        downstream.send()

    start()/stop() are deliberately fail-isolated so notification
    infrastructure can never fail Phoenix runtime lifecycle.
    """

    def __init__(
        self,
        *,
        downstream: NotificationChannel,
        capacity: int = 256,
        poll_seconds: float = 0.05,
        shutdown_join_seconds: float = 1.0,
    ) -> None:
        if (
            type(capacity) is not int
            or capacity <= 0
        ):
            raise ValueError(
                "capacity must be a positive integer"
            )

        if (
            isinstance(
                poll_seconds,
                bool,
            )
            or not isinstance(
                poll_seconds,
                (
                    int,
                    float,
                ),
            )
            or float(
                poll_seconds
            ) <= 0
        ):
            raise ValueError(
                "poll_seconds must be positive"
            )

        if (
            isinstance(
                shutdown_join_seconds,
                bool,
            )
            or not isinstance(
                shutdown_join_seconds,
                (
                    int,
                    float,
                ),
            )
            or float(
                shutdown_join_seconds
            ) <= 0
        ):
            raise ValueError(
                "shutdown_join_seconds must be positive"
            )

        self._downstream = downstream

        self._queue: Queue[
            NotificationMessage
        ] = Queue(
            maxsize=capacity
        )

        self._poll_seconds = float(
            poll_seconds
        )

        self._shutdown_join_seconds = float(
            shutdown_join_seconds
        )

        self._stop_event = Event()
        self._lock = RLock()

        self._thread: Thread | None = None

        # RUNTIME_STARTED is emitted before orchestrator
        # components start, so accept into the queue immediately.
        self._accepting = True

        self._delivered_count = 0
        self._failed_delivery_count = 0
        self._dropped_count = 0

        self._lifecycle_failure_count = 0
        self._last_lifecycle_error: str | None = None

    @property
    def name(
        self,
    ) -> str:
        return "notification-delivery-queue"

    @property
    def downstream(
        self,
    ) -> NotificationChannel:
        return self._downstream

    @property
    def started(
        self,
    ) -> bool:
        with self._lock:
            return (
                self._thread is not None
                and self._thread.is_alive()
            )

    @property
    def pending_count(
        self,
    ) -> int:
        return self._queue.qsize()

    @property
    def delivered_count(
        self,
    ) -> int:
        with self._lock:
            return self._delivered_count

    @property
    def failed_delivery_count(
        self,
    ) -> int:
        with self._lock:
            return self._failed_delivery_count

    @property
    def dropped_count(
        self,
    ) -> int:
        with self._lock:
            return self._dropped_count

    @property
    def lifecycle_failure_count(
        self,
    ) -> int:
        with self._lock:
            return self._lifecycle_failure_count

    @property
    def last_lifecycle_error(
        self,
    ) -> str | None:
        with self._lock:
            return self._last_lifecycle_error

    def snapshot(
        self,
        *,
        captured_at: datetime,
    ) -> NotificationQueueSnapshot:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be datetime"
            )

        with self._lock:
            thread = self._thread

            return NotificationQueueSnapshot(
                started=(
                    thread is not None
                    and thread.is_alive()
                ),
                accepting=(
                    self._accepting
                ),
                capacity=(
                    self._queue.maxsize
                ),
                pending_count=(
                    self._queue.qsize()
                ),
                delivered_count=(
                    self._delivered_count
                ),
                failed_delivery_count=(
                    self._failed_delivery_count
                ),
                dropped_count=(
                    self._dropped_count
                ),
                lifecycle_failure_count=(
                    self._lifecycle_failure_count
                ),
                last_lifecycle_error=(
                    self._last_lifecycle_error
                ),
                captured_at=captured_at,
            )

    def start(
        self,
    ) -> None:
        """
        Start the background worker.

        Idempotent and fail-isolated.
        """

        try:
            with self._lock:
                if (
                    self._thread is not None
                    and self._thread.is_alive()
                ):
                    return

                self._accepting = True
                self._stop_event.clear()

                thread = Thread(
                    target=self._run,
                    name=(
                        "phoenix-notification-delivery"
                    ),
                    daemon=True,
                )

                self._thread = thread

            thread.start()

        except Exception as exc:
            error = (
                f"{type(exc).__name__}: {exc}"
            )

            with self._lock:
                self._thread = None
                self._lifecycle_failure_count += 1
                self._last_lifecycle_error = error

            logger.error(
                "notification worker start failure "
                f"isolated: {error}"
            )

    def stop(
        self,
    ) -> None:
        """
        Stop accepting messages and attempt a bounded drain.

        Idempotent and fail-isolated.
        """

        try:
            with self._lock:
                self._accepting = False
                self._stop_event.set()

                thread = self._thread

            if thread is None:
                return

            if thread is current_thread():
                return

            thread.join(
                timeout=(
                    self._shutdown_join_seconds
                )
            )

            if thread.is_alive():
                logger.warning(
                    "notification delivery worker "
                    "did not finish within bounded "
                    "shutdown window"
                )

        except Exception as exc:
            error = (
                f"{type(exc).__name__}: {exc}"
            )

            with self._lock:
                self._lifecycle_failure_count += 1
                self._last_lifecycle_error = error

            logger.error(
                "notification worker stop failure "
                f"isolated: {error}"
            )

    def send(
        self,
        message: NotificationMessage,
    ) -> NotificationDeliveryResult:
        """
        Queue a notification without blocking.

        This method performs no downstream/network operation.
        """

        if not isinstance(
            message,
            NotificationMessage,
        ):
            raise TypeError(
                "message must be NotificationMessage"
            )

        attempted_at = datetime.now()

        with self._lock:
            accepting = self._accepting

        if not accepting:
            return NotificationDeliveryResult(
                channel=self.name,
                success=False,
                attempted_at=attempted_at,
                error=(
                    "notification delivery queue "
                    "is not accepting messages"
                ),
            )

        try:
            self._queue.put_nowait(
                message
            )

        except Full:
            with self._lock:
                self._dropped_count += 1

            return NotificationDeliveryResult(
                channel=self.name,
                success=False,
                attempted_at=attempted_at,
                error=(
                    "notification delivery queue is full"
                ),
            )

        return NotificationDeliveryResult(
            channel=self.name,
            success=True,
            attempted_at=attempted_at,
        )

    def _run(
        self,
    ) -> None:
        while True:
            if (
                self._stop_event.is_set()
                and self._queue.empty()
            ):
                return

            try:
                message = self._queue.get(
                    timeout=self._poll_seconds
                )

            except Empty:
                continue

            try:
                result = self._downstream.send(
                    message
                )

                if not isinstance(
                    result,
                    NotificationDeliveryResult,
                ):
                    raise TypeError(
                        "downstream notification channel "
                        "returned invalid delivery result"
                    )

                with self._lock:
                    if result.success:
                        self._delivered_count += 1

                    else:
                        self._failed_delivery_count += 1

                if not result.success:
                    logger.warning(
                        "notification transport failed "
                        f"channel={result.channel} "
                        f"notification_id="
                        f"{message.notification_id} "
                        f"error={result.error}"
                    )

            except Exception as exc:
                with self._lock:
                    self._failed_delivery_count += 1

                logger.error(
                    "notification delivery worker "
                    "isolated transport exception "
                    f"notification_id="
                    f"{message.notification_id} "
                    f"error={type(exc).__name__}: {exc}"
                )

            finally:
                self._queue.task_done()


__all__ = [
    "NotificationQueueSnapshot",
    "QueuedNotificationChannel",
]
