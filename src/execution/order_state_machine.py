"""
Phoenix order state machine.

Tracks execution lifecycle independently of immutable OrderIntent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import RLock

from src.execution.execution_types import (
    OrderIntent,
    OrderIntentId,
)


class OrderLifecycleState(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"

    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"

    RECONCILIATION_REQUIRED = (
        "RECONCILIATION_REQUIRED"
    )

    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class OrderStateTransition:
    """
    One immutable order-state transition.
    """

    intent_id: OrderIntentId

    from_state: OrderLifecycleState
    to_state: OrderLifecycleState

    changed_at: datetime

    message: str | None = None


@dataclass(frozen=True, slots=True)
class OrderStateSnapshot:
    """
    Current lifecycle snapshot for one order intent.
    """

    intent_id: OrderIntentId

    current_state: OrderLifecycleState

    created_at: datetime
    updated_at: datetime

    transition_count: int


class OrderStateMachine:
    """
    Tracks valid order lifecycle transitions.

    Terminal states:
        FILLED
        REJECTED
        CANCELLED
        FAILED
    """

    _ALLOWED_TRANSITIONS = {
        OrderLifecycleState.CREATED: {
            OrderLifecycleState.VALIDATED,
            OrderLifecycleState.REJECTED,
            OrderLifecycleState.FAILED,
            OrderLifecycleState.CANCELLED,
        },

        OrderLifecycleState.VALIDATED: {
            OrderLifecycleState.SUBMITTED,
            OrderLifecycleState.REJECTED,
            OrderLifecycleState.FAILED,
            OrderLifecycleState.CANCELLED,
        },

        OrderLifecycleState.SUBMITTED: {
            OrderLifecycleState.PENDING,
            OrderLifecycleState.OPEN,
            OrderLifecycleState.PARTIALLY_FILLED,
            OrderLifecycleState.RECONCILIATION_REQUIRED,
            OrderLifecycleState.FILLED,
            OrderLifecycleState.REJECTED,
            OrderLifecycleState.CANCELLED,
            OrderLifecycleState.FAILED,
        },

        OrderLifecycleState.PENDING: {
            OrderLifecycleState.OPEN,
            OrderLifecycleState.PARTIALLY_FILLED,
            OrderLifecycleState.RECONCILIATION_REQUIRED,
            OrderLifecycleState.FILLED,
            OrderLifecycleState.REJECTED,
            OrderLifecycleState.CANCELLED,
            OrderLifecycleState.FAILED,
        },

        OrderLifecycleState.OPEN: {
            OrderLifecycleState.PARTIALLY_FILLED,
            OrderLifecycleState.RECONCILIATION_REQUIRED,
            OrderLifecycleState.FILLED,
            OrderLifecycleState.CANCELLED,
            OrderLifecycleState.REJECTED,
            OrderLifecycleState.FAILED,
        },

        OrderLifecycleState.PARTIALLY_FILLED: {
            OrderLifecycleState.FILLED,
            OrderLifecycleState.CANCELLED,
            OrderLifecycleState.FAILED,
            OrderLifecycleState.RECONCILIATION_REQUIRED,
        },

        OrderLifecycleState.RECONCILIATION_REQUIRED: {
            OrderLifecycleState.PENDING,
            OrderLifecycleState.OPEN,
            OrderLifecycleState.PARTIALLY_FILLED,
            OrderLifecycleState.FILLED,
            OrderLifecycleState.REJECTED,
            OrderLifecycleState.CANCELLED,
            OrderLifecycleState.FAILED,
        },

        OrderLifecycleState.FILLED: set(),
        OrderLifecycleState.REJECTED: set(),
        OrderLifecycleState.CANCELLED: set(),
        OrderLifecycleState.FAILED: set(),
    }

    _TERMINAL_STATES = {
        OrderLifecycleState.FILLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.FAILED,
    }

    def __init__(self) -> None:
        self._states: dict[
            str,
            OrderLifecycleState,
        ] = {}

        self._created_at: dict[
            str,
            datetime,
        ] = {}

        self._updated_at: dict[
            str,
            datetime,
        ] = {}

        self._history: dict[
            str,
            list[OrderStateTransition],
        ] = {}

        self._lock = RLock()

    def register(
        self,
        intent: OrderIntent,
    ) -> None:
        """
        Register a newly created order intent.
        """

        key = intent.intent_id.value

        with self._lock:
            if key in self._states:
                raise RuntimeError(
                    f"order intent already registered: {key}"
                )

            self._states[key] = (
                OrderLifecycleState.CREATED
            )

            self._created_at[key] = (
                intent.created_at
            )

            self._updated_at[key] = (
                intent.created_at
            )

            self._history[key] = []

    def transition(
        self,
        intent_id: OrderIntentId,
        to_state: OrderLifecycleState,
        changed_at: datetime,
        message: str | None = None,
    ) -> OrderStateTransition:
        """
        Apply one validated order-state transition.
        """

        key = intent_id.value

        with self._lock:
            if key not in self._states:
                raise KeyError(
                    f"order intent not registered: {key}"
                )

            current = self._states[key]

            if to_state is current:
                raise RuntimeError(
                    f"order already in state {to_state.value}"
                )

            allowed = self._ALLOWED_TRANSITIONS[
                current
            ]

            if to_state not in allowed:
                raise RuntimeError(
                    "invalid order state transition: "
                    f"{current.value} -> {to_state.value}"
                )

            normalized_message = (
                message.strip()
                if message is not None
                else None
            )

            if (
                message is not None
                and not normalized_message
            ):
                raise ValueError(
                    "message cannot be empty"
                )

            transition = OrderStateTransition(
                intent_id=intent_id,
                from_state=current,
                to_state=to_state,
                changed_at=changed_at,
                message=normalized_message,
            )

            self._states[key] = to_state
            self._updated_at[key] = changed_at
            self._history[key].append(
                transition
            )

            return transition

    def get_state(
        self,
        intent_id: OrderIntentId,
    ) -> OrderLifecycleState:
        """
        Return current state.
        """

        key = intent_id.value

        with self._lock:
            if key not in self._states:
                raise KeyError(
                    f"order intent not registered: {key}"
                )

            return self._states[key]

    def get_history(
        self,
        intent_id: OrderIntentId,
    ) -> tuple[OrderStateTransition, ...]:
        """
        Return immutable transition history.
        """

        key = intent_id.value

        with self._lock:
            if key not in self._history:
                raise KeyError(
                    f"order intent not registered: {key}"
                )

            return tuple(
                self._history[key]
            )

    def snapshot(
        self,
        intent_id: OrderIntentId,
    ) -> OrderStateSnapshot:
        """
        Return current order lifecycle snapshot.
        """

        key = intent_id.value

        with self._lock:
            if key not in self._states:
                raise KeyError(
                    f"order intent not registered: {key}"
                )

            return OrderStateSnapshot(
                intent_id=intent_id,
                current_state=self._states[key],
                created_at=self._created_at[key],
                updated_at=self._updated_at[key],
                transition_count=len(
                    self._history[key]
                ),
            )

    def is_terminal(
        self,
        intent_id: OrderIntentId,
    ) -> bool:
        """
        Return True when order cannot transition further.
        """

        state = self.get_state(
            intent_id
        )

        return (
            state
            in self._TERMINAL_STATES
        )

    def count(self) -> int:
        with self._lock:
            return len(
                self._states
            )

    def restore_state(
        self,
        *,
        intent_id: OrderIntentId,
        current_state: OrderLifecycleState,
        created_at: datetime,
        updated_at: datetime,
    ) -> OrderStateSnapshot:
        """
        Restore the authoritative current lifecycle state of
        one durable order.

        Recovery does not fabricate historical transitions.
        Therefore a newly restored order has transition_count
        zero while preserving its exact current state and
        timestamps.

        Identical replay is idempotent; conflicting replay
        fails closed.
        """

        if not isinstance(
            intent_id,
            OrderIntentId,
        ):
            raise TypeError(
                "intent_id must be OrderIntentId"
            )

        if not isinstance(
            current_state,
            OrderLifecycleState,
        ):
            raise TypeError(
                "current_state must be "
                "OrderLifecycleState"
            )

        if type(created_at) is not datetime:
            raise TypeError(
                "created_at must be a datetime"
            )

        if type(updated_at) is not datetime:
            raise TypeError(
                "updated_at must be a datetime"
            )

        if updated_at < created_at:
            raise ValueError(
                "order recovery updated_at cannot "
                "be before created_at"
            )

        key = intent_id.value

        with self._lock:
            if key in self._states:
                existing = OrderStateSnapshot(
                    intent_id=intent_id,
                    current_state=(
                        self._states[key]
                    ),
                    created_at=(
                        self._created_at[key]
                    ),
                    updated_at=(
                        self._updated_at[key]
                    ),
                    transition_count=len(
                        self._history[key]
                    ),
                )

                if (
                    existing.current_state
                    is not current_state
                    or existing.created_at
                    != created_at
                    or existing.updated_at
                    != updated_at
                ):
                    raise RuntimeError(
                        "conflicting order lifecycle "
                        "recovery state: "
                        f"{key}"
                    )

                return existing

            self._states[key] = (
                current_state
            )

            self._created_at[key] = (
                created_at
            )

            self._updated_at[key] = (
                updated_at
            )

            self._history[key] = []

            return OrderStateSnapshot(
                intent_id=intent_id,
                current_state=current_state,
                created_at=created_at,
                updated_at=updated_at,
                transition_count=0,
            )

    def clear(self) -> None:
        """
        Controlled test/session reset only.
        """

        with self._lock:
            self._states.clear()
            self._created_at.clear()
            self._updated_at.clear()
            self._history.clear()
