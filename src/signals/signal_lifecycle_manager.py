"""
Signal lifecycle tracking for Phoenix Trading Platform.

Tracks signal state transitions separately from the immutable
TradingSignal domain object.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from src.signals.signal_types import (
    SignalId,
    SignalState,
    TradingSignal,
)


@dataclass(frozen=True, slots=True)
class SignalStateTransition:
    """
    One immutable signal-state transition.
    """

    signal_id: SignalId
    from_state: SignalState
    to_state: SignalState
    changed_at: datetime
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SignalLifecycleSnapshot:
    """
    Current lifecycle state for one signal.
    """

    signal_id: SignalId
    current_state: SignalState
    created_at: datetime
    updated_at: datetime
    transition_count: int


class SignalLifecycleManager:
    """
    Tracks lifecycle state transitions for TradingSignal objects.

    TradingSignal itself remains immutable.

    Valid transitions:

        CREATED -> QUEUED
        CREATED -> REJECTED
        CREATED -> CANCELLED

        QUEUED -> ACCEPTED
        QUEUED -> REJECTED
        QUEUED -> CANCELLED

        ACCEPTED -> CONSUMED
        ACCEPTED -> CANCELLED

    Terminal states:

        REJECTED
        CONSUMED
        CANCELLED
    """

    _ALLOWED_TRANSITIONS = {
        SignalState.CREATED: {
            SignalState.QUEUED,
            SignalState.REJECTED,
            SignalState.CANCELLED,
        },
        SignalState.QUEUED: {
            SignalState.ACCEPTED,
            SignalState.REJECTED,
            SignalState.CANCELLED,
        },
        SignalState.ACCEPTED: {
            SignalState.CONSUMED,
            SignalState.CANCELLED,
        },
        SignalState.REJECTED: set(),
        SignalState.CONSUMED: set(),
        SignalState.CANCELLED: set(),
    }

    def __init__(self) -> None:
        self._states: dict[str, SignalState] = {}
        self._created_at: dict[str, datetime] = {}
        self._updated_at: dict[str, datetime] = {}
        self._history: dict[
            str,
            list[SignalStateTransition],
        ] = {}

        self._lock = RLock()

    def register(
        self,
        signal: TradingSignal,
    ) -> None:
        """
        Register a newly created signal.

        Duplicate signal IDs are rejected.
        """

        signal_key = signal.signal_id.value

        with self._lock:
            if signal_key in self._states:
                raise RuntimeError(
                    f"signal already registered: {signal_key}"
                )

            self._states[signal_key] = signal.state
            self._created_at[signal_key] = signal.generated_at
            self._updated_at[signal_key] = signal.generated_at
            self._history[signal_key] = []

    def transition(
        self,
        signal_id: SignalId,
        to_state: SignalState,
        changed_at: datetime,
        reason: str | None = None,
    ) -> SignalStateTransition:
        """
        Apply one validated signal lifecycle transition.
        """

        signal_key = signal_id.value

        with self._lock:
            if signal_key not in self._states:
                raise KeyError(
                    f"signal not registered: {signal_key}"
                )

            current_state = self._states[signal_key]

            if to_state is current_state:
                raise RuntimeError(
                    f"signal already in state {to_state.value}"
                )

            allowed = self._ALLOWED_TRANSITIONS[
                current_state
            ]

            if to_state not in allowed:
                raise RuntimeError(
                    "invalid signal state transition: "
                    f"{current_state.value} -> {to_state.value}"
                )

            normalized_reason = (
                reason.strip()
                if reason is not None
                else None
            )

            if reason is not None and not normalized_reason:
                raise ValueError(
                    "reason cannot be empty"
                )

            transition = SignalStateTransition(
                signal_id=signal_id,
                from_state=current_state,
                to_state=to_state,
                changed_at=changed_at,
                reason=normalized_reason,
            )

            self._states[signal_key] = to_state
            self._updated_at[signal_key] = changed_at
            self._history[signal_key].append(
                transition
            )

            return transition

    def get_state(
        self,
        signal_id: SignalId,
    ) -> SignalState:
        """
        Return current state for a registered signal.
        """

        with self._lock:
            try:
                return self._states[
                    signal_id.value
                ]

            except KeyError as exc:
                raise KeyError(
                    f"signal not registered: "
                    f"{signal_id.value}"
                ) from exc

    def get_history(
        self,
        signal_id: SignalId,
    ) -> tuple[SignalStateTransition, ...]:
        """
        Return immutable transition history.
        """

        with self._lock:
            if signal_id.value not in self._history:
                raise KeyError(
                    f"signal not registered: "
                    f"{signal_id.value}"
                )

            return tuple(
                self._history[
                    signal_id.value
                ]
            )

    def snapshot(
        self,
        signal_id: SignalId,
    ) -> SignalLifecycleSnapshot:
        """
        Return lifecycle snapshot for one signal.
        """

        signal_key = signal_id.value

        with self._lock:
            if signal_key not in self._states:
                raise KeyError(
                    f"signal not registered: {signal_key}"
                )

            return SignalLifecycleSnapshot(
                signal_id=signal_id,
                current_state=self._states[
                    signal_key
                ],
                created_at=self._created_at[
                    signal_key
                ],
                updated_at=self._updated_at[
                    signal_key
                ],
                transition_count=len(
                    self._history[
                        signal_key
                    ]
                ),
            )

    def is_terminal(
        self,
        signal_id: SignalId,
    ) -> bool:
        """
        Return True when the signal can no longer transition.
        """

        state = self.get_state(signal_id)

        return state in {
            SignalState.REJECTED,
            SignalState.CONSUMED,
            SignalState.CANCELLED,
        }

    def count(self) -> int:
        """
        Return number of registered signals.
        """

        with self._lock:
            return len(self._states)

    def clear(self) -> None:
        """
        Clear all lifecycle state.

        Intended for controlled session/test reset only.
        """

        with self._lock:
            self._states.clear()
            self._created_at.clear()
            self._updated_at.clear()
            self._history.clear()