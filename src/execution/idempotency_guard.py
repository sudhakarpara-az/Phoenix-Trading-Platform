"""
Phoenix execution idempotency / duplicate-order guard.

Prevents the same logical execution request from creating
multiple broker orders.

The guard is broker-independent, thread-safe, and can be used
for both entry BUY intents and exit SELL intents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import RLock
from typing import Any

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
    """
    Current idempotency state for one logical execution.

    intent_id is stored as a plain string so the same guard
    can support:

        OrderIntentId
        ExitOrderIntentId
    """

    key: IdempotencyKey

    state: IdempotencyState

    intent_id: str | None

    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IdempotencyReservationResult:
    acquired: bool

    key: IdempotencyKey

    existing_record: IdempotencyRecord | None = None


class DuplicateOrderGuard:
    """
    Thread-safe execution idempotency guard.

    Lifecycle:

        reserve()
            ↓
        RESERVED
            ↓
        attach_intent() / attach_intent_id()
            ↓
        mark_submitted()
            ↓
        SUBMITTED
            ↓
        mark_completed()
            ↓
        COMPLETED

    If no broker submission occurred:

        RESERVED
            ↓
        release()
            ↓
        RELEASED

    RELEASED keys may later be reserved again.

    SUBMITTED and COMPLETED keys must never be released
    automatically.
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

        Returns acquired=False if an active/completed
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

    def attach_intent_id(
        self,
        *,
        key: IdempotencyKey,
        intent_id: str,
        changed_at: datetime,
    ) -> IdempotencyRecord:
        """
        Associate a plain intent identifier with a reservation.

        Used by both entry and exit execution services.
        """

        if not intent_id.strip():
            raise ValueError(
                "intent_id cannot be empty"
            )

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
                intent_id=intent_id,
                created_at=record.created_at,
                updated_at=changed_at,
            )

            self._records[key.value] = updated

            return updated

    def attach_intent(
        self,
        *,
        key: IdempotencyKey,
        intent: Any,
        changed_at: datetime,
    ) -> IdempotencyRecord:
        """
        Backward-compatible helper.

        Supports existing Phoenix entry OrderIntent objects
        and any future intent object exposing:

            intent.intent_id.value
        """

        if not hasattr(
            intent,
            "intent_id",
        ):
            raise ValueError(
                "intent must contain intent_id"
            )

        intent_id = intent.intent_id

        if not hasattr(
            intent_id,
            "value",
        ):
            raise ValueError(
                "intent.intent_id must contain value"
            )

        return self.attach_intent_id(
            key=key,
            intent_id=str(
                intent_id.value
            ),
            changed_at=changed_at,
        )

    def mark_submitted(
        self,
        *,
        key: IdempotencyKey,
        changed_at: datetime,
    ) -> IdempotencyRecord:
        """
        Mark that broker submission has been attempted.

        Once SUBMITTED, this key cannot safely be released
        automatically because the broker order may exist.
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
        Complete one logical execution.

        COMPLETED keys block future duplicate submissions.
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

        Only RESERVED records may be released.
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

    def release_after_reconciliation(
        self,
        *,
        key: IdempotencyKey,
        changed_at: datetime,
    ) -> IdempotencyRecord:
        """
        Explicitly release a SUBMITTED idempotency key after
        external broker reconciliation proves that the previous
        order can no longer execute.

        This method must only be called after Phoenix has
        confirmed the broker order is CANCELLED.

        Normal code must continue using release(), which permits
        only RESERVED -> RELEASED.
        """

        with self._lock:
            record = self._require_record(
                key
            )

            if (
                record.state
                is not IdempotencyState.SUBMITTED
            ):
                raise RuntimeError(
                    "only SUBMITTED idempotency key "
                    "can be reconciliation-released"
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
        True when another order must not be generated
        for this logical execution key.
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
        Controlled test/session reset helper.
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