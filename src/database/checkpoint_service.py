"""
Phoenix M08 persistence checkpoint implementation.

Bridges:

    RuntimeSnapshot
    RuntimeEvent

to durable database records.

Responsibilities:
    - create/update runtime session checkpoints
    - persist runtime events as audit events
    - serialize event payloads safely
    - provide explicit database failure boundary

This module may know about both runtime domain objects and
database persistence records.

M03-M07 remain unaware of persistence implementation details.
"""

from __future__ import annotations

from dataclasses import (
    asdict,
    is_dataclass,
)
from datetime import (
    date,
    datetime,
)
from enum import Enum
import json
from typing import Any

from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyAuditEventRepository,
    SQLAlchemyRuntimeSessionRepository,
)
from src.database.schema import (
    AuditEventRecord,
    RuntimeSessionRecord,
)
from src.runtime.runtime_events import (
    RuntimeEvent,
    RuntimeEventType,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeSnapshot,
)


class PersistenceCheckpointError(
    RuntimeError
):
    """
    Persistence operation failed.

    Future runtime orchestration must treat this as safety
    critical and fail closed for new entries.
    """


class SQLAlchemyCheckpointService:
    """
    Durable Phoenix runtime checkpoint service.
    """

    def __init__(
        self,
        *,
        runtime_repository:
            SQLAlchemyRuntimeSessionRepository,
        audit_repository:
            SQLAlchemyAuditEventRepository,
    ) -> None:
        self._runtime_repository = (
            runtime_repository
        )

        self._audit_repository = (
            audit_repository
        )

    # ========================================================
    # Runtime state
    # ========================================================

    def checkpoint_runtime(
        self,
        snapshot: RuntimeSnapshot,
    ) -> None:
        """
        Persist current RuntimeSnapshot.

        First checkpoint:
            INSERT

        Later checkpoints:
            UPDATE

        This is an intentional state checkpoint operation,
        not repository-level implicit upsert behavior.
        """

        try:
            record = self._runtime_record(
                snapshot
            )

            existing = (
                self._runtime_repository.get(
                    snapshot.runtime_id.value
                )
            )

            if existing is None:
                self._runtime_repository.add(
                    record
                )

            else:
                self._runtime_repository.update(
                    record
                )

        except Exception as exc:
            raise PersistenceCheckpointError(
                "runtime checkpoint failed: "
                f"{exc}"
            ) from exc

    def runtime_exists(
        self,
        runtime_id: str,
    ) -> bool:
        try:
            return (
                self._runtime_repository.get(
                    runtime_id
                )
                is not None
            )

        except Exception as exc:
            raise PersistenceCheckpointError(
                "runtime existence check failed: "
                f"{exc}"
            ) from exc

    # ========================================================
    # Runtime event audit
    # ========================================================

    def checkpoint_event(
        self,
        event: RuntimeEvent,
    ) -> None:
        """
        Persist a RuntimeEvent as an append-oriented audit row.

        RuntimeEvent.event_id becomes AuditEventRecord.event_id,
        preserving one stable event identity.
        """

        try:
            record = AuditEventRecord(
                event_id=event.event_id,
                runtime_id=(
                    event.runtime_id.value
                ),
                event_type=(
                    event.event_type.value
                ),
                entity_type=(
                    self._entity_type(
                        event
                    )
                ),
                entity_id=(
                    self._entity_id(
                        event
                    )
                ),
                message=None,
                payload=(
                    self._serialize_payload(
                        event
                    )
                ),
                occurred_at=event.occurred_at,
            )

            self._audit_repository.add(
                record
            )

        except Exception as exc:
            raise PersistenceCheckpointError(
                "runtime event checkpoint failed: "
                f"{exc}"
            ) from exc

    # ========================================================
    # Mapping
    # ========================================================

    @staticmethod
    def _runtime_record(
        snapshot: RuntimeSnapshot,
    ) -> RuntimeSessionRecord:
        failure = snapshot.failure

        return RuntimeSessionRecord(
            runtime_id=(
                snapshot.runtime_id.value
            ),
            trading_date=(
                snapshot.trading_date
            ),
            mode=snapshot.mode.value,
            state=snapshot.state.value,
            started_at=(
                snapshot.started_at
            ),
            updated_at=(
                snapshot.updated_at
            ),
            stopped_at=(
                snapshot.stopped_at
            ),
            recovery_required=(
                snapshot.recovery_required
            ),
            recovered=(
                snapshot.recovered
            ),
            failure_code=(
                failure.code.value
                if failure is not None
                else None
            ),
            failure_message=(
                failure.message
                if failure is not None
                else None
            ),
            failure_component=(
                failure.component
                if failure is not None
                else None
            ),
            failure_occurred_at=(
                failure.occurred_at
                if failure is not None
                else None
            ),
            failure_recoverable=(
                failure.recoverable
                if failure is not None
                else None
            ),
        )

    # ========================================================
    # Audit serialization
    # ========================================================

    @classmethod
    def _serialize_payload(
        cls,
        event: RuntimeEvent,
    ) -> str:
        """
        Persist event envelope information plus opaque payload.

        Correlation and causation data are stored here until a
        future schema migration decides they warrant dedicated
        indexed columns.
        """

        envelope = {
            "correlation_id": (
                event.correlation_id
            ),
            "causation_id": (
                event.causation_id
            ),
            "payload": event.payload,
        }

        return json.dumps(
            envelope,
            default=cls._json_default,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

    @staticmethod
    def _json_default(
        value: Any,
    ) -> Any:
        if isinstance(
            value,
            Enum,
        ):
            return value.value

        if isinstance(
            value,
            (
                datetime,
                date,
            ),
        ):
            return value.isoformat()

        if isinstance(
            value,
            RuntimeId,
        ):
            return value.value

        if is_dataclass(
            value
        ):
            return asdict(
                value
            )

        if hasattr(
            value,
            "value",
        ):
            candidate = getattr(
                value,
                "value"
            )

            if isinstance(
                candidate,
                (
                    str,
                    int,
                    float,
                    bool,
                ),
            ):
                return candidate

        return str(
            value
        )

    # ========================================================
    # Lightweight audit entity extraction
    # ========================================================

    @staticmethod
    def _entity_type(
        event: RuntimeEvent,
    ) -> str | None:
        payload = event.payload

        if not isinstance(
            payload,
            dict,
        ):
            return None

        value = payload.get(
            "entity_type"
        )

        if value is None:
            return None

        return str(
            value
        )

    @staticmethod
    def _entity_id(
        event: RuntimeEvent,
    ) -> str | None:
        payload = event.payload

        if not isinstance(
            payload,
            dict,
        ):
            return None

        value = payload.get(
            "entity_id"
        )

        if value is None:
            return None

        return str(
            value
        )
class RuntimeEventAuditSubscriber:
    """
    RuntimeEventBus subscriber that durably checkpoints every
    event it receives.

    Subscribe this instance to the required event types during
    M08 runtime wiring.

    The EventBus remains persistence-agnostic.
    """

    def __init__(
        self,
        *,
        checkpoint_service: SQLAlchemyCheckpointService,
    ) -> None:
        self._checkpoint_service = checkpoint_service

    def __call__(self, event: RuntimeEvent) -> None:
        self._checkpoint_service.checkpoint_event(event)

    def subscribe_all(self, event_bus) -> None:
        """
        Subscribe audit persistence to every current RuntimeEventType.

        RuntimeEventBus duplicate subscription protection makes this
        operation safely repeatable.
        """

        for event_type in RuntimeEventType:
            event_bus.subscribe(event_type, self)