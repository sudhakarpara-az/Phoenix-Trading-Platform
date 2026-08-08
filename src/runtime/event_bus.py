"""
Phoenix M08 synchronous runtime event bus.

Responsibilities:
    - subscribe handlers to typed RuntimeEventType values
    - unsubscribe handlers
    - deterministic synchronous event dispatch
    - preserve subscription order
    - prevent duplicate subscription
    - track publish results
    - surface handler failures safely

Important:

    M08-T05 does NOT swallow handler exceptions by default.

    Trading-runtime failures must be visible to the future
    orchestrator so it can fail closed rather than silently
    continue after a broken component.

No background threads or async execution belong here.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import (
    Callable,
    Protocol,
)

from src.runtime.runtime_events import (
    RuntimeEvent,
    RuntimeEventType,
)


class RuntimeEventHandler(
    Protocol,
):
    def __call__(
        self,
        event: RuntimeEvent,
    ) -> None:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class EventDispatchFailure:
    """
    One subscriber failure during publication.
    """

    handler_name: str

    exception: Exception


@dataclass(
    frozen=True,
    slots=True,
)
class EventDispatchResult:
    """
    Outcome of publishing one RuntimeEvent.
    """

    event: RuntimeEvent

    subscriber_count: int

    delivered_count: int

    failures: tuple[
        EventDispatchFailure,
        ...
    ]

    @property
    def successful(
        self,
    ) -> bool:
        return not self.failures

    @property
    def failed_count(
        self,
    ) -> int:
        return len(
            self.failures
        )


class RuntimeEventDispatchError(
    RuntimeError
):
    """
    Raised when strict event dispatch encounters a subscriber
    failure.

    The partial dispatch result is retained so the orchestrator
    can inspect exactly how far delivery progressed.
    """

    def __init__(
        self,
        result: EventDispatchResult,
    ) -> None:
        self.result = result

        first_failure = (
            result.failures[0]
        )

        super().__init__(
            "runtime event dispatch failed: "
            f"{result.event.event_type.value} -> "
            f"{first_failure.handler_name}: "
            f"{first_failure.exception}"
        )


class RuntimeEventBus:
    """
    Thread-safe synchronous Phoenix event dispatcher.

    Handler invocation happens in subscription order.

    The lock protects subscription state only. User handlers are
    never called while the bus lock is held.
    """

    def __init__(
        self,
        *,
        strict: bool = True,
    ) -> None:
        self._strict = strict

        self._subscriptions: dict[
            RuntimeEventType,
            list[RuntimeEventHandler],
        ] = {}

        self._lock = RLock()

    @property
    def strict(
        self,
    ) -> bool:
        return self._strict

    def subscribe(
        self,
        event_type: RuntimeEventType,
        handler: RuntimeEventHandler,
    ) -> bool:
        """
        Subscribe a handler.

        Returns:
            True  -> newly subscribed
            False -> handler was already subscribed

        Duplicate handler registration is intentionally
        idempotent to prevent duplicate trading actions.
        """

        if not callable(
            handler
        ):
            raise TypeError(
                "runtime event handler must be callable"
            )

        with self._lock:
            handlers = (
                self._subscriptions
                .setdefault(
                    event_type,
                    [],
                )
            )

            if handler in handlers:
                return False

            handlers.append(
                handler
            )

            return True

    def unsubscribe(
        self,
        event_type: RuntimeEventType,
        handler: RuntimeEventHandler,
    ) -> bool:
        """
        Remove a specific event subscription.

        Returns False if it did not exist.
        """

        with self._lock:
            handlers = (
                self._subscriptions.get(
                    event_type
                )
            )

            if not handlers:
                return False

            try:
                handlers.remove(
                    handler
                )

            except ValueError:
                return False

            if not handlers:
                del self._subscriptions[
                    event_type
                ]

            return True

    def subscribers(
        self,
        event_type: RuntimeEventType,
    ) -> tuple[
        RuntimeEventHandler,
        ...
    ]:
        """
        Return immutable current subscriber snapshot.
        """

        with self._lock:
            return tuple(
                self._subscriptions.get(
                    event_type,
                    ()
                )
            )

    def subscriber_count(
        self,
        event_type: RuntimeEventType,
    ) -> int:
        return len(
            self.subscribers(
                event_type
            )
        )

    def publish(
        self,
        event: RuntimeEvent,
    ) -> EventDispatchResult:
        """
        Publish synchronously.

        strict=True:
            Stop at the first failing handler and raise
            RuntimeEventDispatchError.

        strict=False:
            Continue delivering to remaining subscribers and
            return all failures in EventDispatchResult.
        """

        handlers = self.subscribers(
            event.event_type
        )

        delivered_count = 0

        failures: list[
            EventDispatchFailure
        ] = []

        for handler in handlers:
            try:
                handler(
                    event
                )

                delivered_count += 1

            except Exception as exc:
                failure = EventDispatchFailure(
                    handler_name=(
                        self._handler_name(
                            handler
                        )
                    ),
                    exception=exc,
                )

                failures.append(
                    failure
                )

                if self._strict:
                    result = (
                        EventDispatchResult(
                            event=event,
                            subscriber_count=(
                                len(handlers)
                            ),
                            delivered_count=(
                                delivered_count
                            ),
                            failures=tuple(
                                failures
                            ),
                        )
                    )

                    raise (
                        RuntimeEventDispatchError(
                            result
                        )
                    ) from exc

        return EventDispatchResult(
            event=event,
            subscriber_count=len(
                handlers
            ),
            delivered_count=(
                delivered_count
            ),
            failures=tuple(
                failures
            ),
        )

    def clear(
        self,
    ) -> None:
        """
        Remove every subscription.

        Primarily useful during runtime shutdown and isolated
        testing.
        """

        with self._lock:
            self._subscriptions.clear()

    @staticmethod
    def _handler_name(
        handler: RuntimeEventHandler,
    ) -> str:
        name = getattr(
            handler,
            "__qualname__",
            None,
        )

        if name:
            return str(
                name
            )

        name = getattr(
            handler,
            "__name__",
            None,
        )

        if name:
            return str(
                name
            )

        return (
            handler.__class__.__name__
        )