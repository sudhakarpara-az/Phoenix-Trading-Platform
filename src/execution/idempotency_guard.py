"""
Phoenix execution idempotency / duplicate-order guard.

Prevents the same logical strategy signal from creating
multiple broker BUY orders.

The guard is broker-independent and thread-safe.
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
from src.signals.signal_types import SignalId


class IdempotencyState(str, Enum):
    RESERVED = "RESERVED"
    SUBMITTED = "SUBMITTED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """
    Stable logical execution identity.

    For current Phoenix architecture, one signal ID should
    produce at most one entry order.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError(
                "idempotency key cannot be empty"
            )

    @classmethod
    def from_signal_id(
        cls,
        signal_id: SignalId,
    ) -> "IdempotencyKey":
        return cls(
            value=f"SIGNAL:{signal_id.value}"
        )


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: IdempotencyKey

    state: IdempotencyState

    intent_id: OrderIntentId | None

    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IdempotencyReservationResult:
    acquired: bool

    key: IdempotencyKey

    existing_record: IdempotencyRecord | None = None


class DuplicateOrderGuard:
    """
    Thread-safe idempotency guard.

    Lifecycle:

        reserve()
            ↓
        RESERVED
            ↓
        mark_submitted()
            ↓
        SUBMITTED
            ↓
        mark_completed()
            ↓
        COMPLETED

    If no broker submission happened, a RESERVED key may be:

        release()
            ↓
        RELEASED

    A released key may later be reserved again.
    """

    def __init__(self) -> None:
        self._records: dict[
            str,
            IdempotencyRecord,
        ] = {}

        self._lock = RLock()

    def reserve(
        self,
        *,
        key: IdempotencyKey,
        created_at: datetime,
    ) -> IdempotencyReservationResult:
        """
        Atomically reserve one logical execution key.

        Returns acquired=False when an active or completed
        reservation already exists.
        """

        with self._lock:
            existing = self._records.get(
                key.value
            )

            if (
                existing is not None
                and existing.state
                is not IdempotencyState.RELEASED
            ):
                return IdempotencyReservationResult(
                    acquired=False,
                    key=key,
                    existing_record=existing,
                )

            record = IdempotencyRecord(
                key=key,
                state=IdempotencyState.RESERVED,
                intent_id=None,
                created_at=created_at,
                updated_at=created_at,
            )

            self._records[key.value] = record

            return IdempotencyReservationResult(
                acquired=True,
                key=key,
                existing_record=None,
            )

    def attach_intent(
        self,
        *,
        key: IdempotencyKey,
        intent: OrderIntent,
        changed_at: datetime,
    ) -> IdempotencyRecord:
        """
        Associate the generated OrderIntent with a reservation.
        """

        with self._lock:
            record = self._require_record(
                key
            )

            if (
                record.state
                is not IdempotencyState.RESERVED
            ):
                raise RuntimeError(
                    "intent can only be attached "
                    "to RESERVED idempotency key"
                )

            if record.intent_id is not None:
                raise RuntimeError(
                    "idempotency key already has an intent"
                )

            updated = IdempotencyRecord(
                key=record.key,
                state=record.state,
                intent_id=intent.intent_id,
                created_at=record.created_at,
                updated_at=changed_at,
            )

            self._records[key.value] = updated

            return updated

    def mark_submitted(
        self,
        *,
        key: IdempotencyKey,
        changed_at: datetime,
    ) -> IdempotencyRecord:
        """
        Mark that the order reached broker submission.
        """

        with self._lock:
            record = self._require_record(
                key
            )

            if (
                record.state
                is not IdempotencyState.RESERVED
            ):
                raise RuntimeError(
                    "only RESERVED key can become SUBMITTED"
                )

            if record.intent_id is None:
                raise RuntimeError(
                    "cannot submit idempotency key "
                    "without attached intent"
                )

            updated = IdempotencyRecord(
                key=record.key,
                state=IdempotencyState.SUBMITTED,
                intent_id=record.intent_id,
                created_at=record.created_at,
                updated_at=changed_at,
            )

            self._records[key.value] = updated

            return updated

    def mark_completed(
        self,
        *,
        key: IdempotencyKey,
        changed_at: datetime,
    ) -> IdempotencyRecord:
        """
        Permanently complete the logical entry execution.

        COMPLETED keys cannot be reused.
        """

        with self._lock:
            record = self._require_record(
                key
            )

            if record.state not in {
                IdempotencyState.RESERVED,
                IdempotencyState.SUBMITTED,
            }:
                raise RuntimeError(
                    "idempotency key cannot become COMPLETED "
                    f"from {record.state.value}"
                )

            updated = IdempotencyRecord(
                key=record.key,
                state=IdempotencyState.COMPLETED,
                intent_id=record.intent_id,
                created_at=record.created_at,
                updated_at=changed_at,
            )

            self._records[key.value] = updated

            return updated

    def release(
        self,
        *,
        key: IdempotencyKey,
        changed_at: datetime,
    ) -> IdempotencyRecord:
        """
        Release an unused reservation.

        Safety rule:
        SUBMITTED and COMPLETED keys must never be released,
        because doing so could create a second broker order
        while the first order may still exist.
        """

        with self._lock:
            record = self._require_record(
                key
            )

            if (
                record.state
                is not IdempotencyState.RESERVED
            ):
                raise RuntimeError(
                    "only RESERVED idempotency key "
                    "can be released"
                )

            updated = IdempotencyRecord(
                key=record.key,
                state=IdempotencyState.RELEASED,
                intent_id=record.intent_id,
                created_at=record.created_at,
                updated_at=changed_at,
            )

            self._records[key.value] = updated

            return updated

    def get(
        self,
        key: IdempotencyKey,
    ) -> IdempotencyRecord | None:
        with self._lock:
            return self._records.get(
                key.value
            )

    def is_blocked(
        self,
        key: IdempotencyKey,
    ) -> bool:
        """
        True when a key must not produce another order.
        """

        with self._lock:
            record = self._records.get(
                key.value
            )

            if record is None:
                return False

            return (
                record.state
                is not IdempotencyState.RELEASED
            )

    def count(self) -> int:
        with self._lock:
            return len(
                self._records
            )

    def clear(self) -> None:
        """
        Test/session reset helper.
        """

        with self._lock:
            self._records.clear()

    def _require_record(
        self,
        key: IdempotencyKey,
    ) -> IdempotencyRecord:
        record = self._records.get(
            key.value
        )

        if record is None:
            raise KeyError(
                "idempotency key not reserved: "
                f"{key.value}"
            )

        return record