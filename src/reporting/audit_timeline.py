"""
Phoenix M12 durable runtime audit timeline.

The timeline reads the existing M08 AuditEventRecord stream.

Persisted arbitrary payload content is not exposed. Only stable
audit metadata plus correlation/causation linkage is projected.
"""

from __future__ import annotations

import json

from typing import Protocol

from src.database.schema import (
    AuditEventRecord,
)
from src.reporting.reporting_types import (
    AuditTimelineEntry,
)


class AuditTimelineIntegrityError(
    RuntimeError,
):
    """
    Durable audit data is inconsistent with the requested report.
    """


class _AuditRepositoryReader(
    Protocol,
):
    """
    Narrow read-only view of the existing audit repository.
    """

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        AuditEventRecord,
        ...,
    ]:
        ...


class AuditTimelineService:
    """
    Project durable audit rows into a safe reporting timeline.
    """

    def __init__(
        self,
        *,
        audit_repository: _AuditRepositoryReader,
    ) -> None:
        self._repository = audit_repository

    @property
    def repository(
        self,
    ) -> _AuditRepositoryReader:
        return self._repository

    def list_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        AuditTimelineEntry,
        ...,
    ]:
        runtime_id = self._normalize_runtime_id(
            runtime_id
        )

        records = tuple(
            self._repository.list_by_runtime(
                runtime_id
            )
        )

        entries = tuple(
            self._to_entry(
                runtime_id=runtime_id,
                record=record,
            )
            for record in records
        )

        # Existing SQLAlchemy repository already orders by
        # occurred_at. Sort defensively so alternate read ports
        # preserve deterministic M12 output as well.
        return tuple(
            sorted(
                entries,
                key=lambda item: (
                    item.occurred_at,
                    item.event_id,
                ),
            )
        )

    def _to_entry(
        self,
        *,
        runtime_id: str,
        record: AuditEventRecord,
    ) -> AuditTimelineEntry:
        if record.runtime_id != runtime_id:
            raise AuditTimelineIntegrityError(
                "audit event runtime_id does not match "
                f"requested runtime: {record.event_id}"
            )

        (
            correlation_id,
            causation_id,
        ) = self._extract_links(
            record.payload
        )

        message = self._optional_text(
            record.message,
            limit=1000,
        )

        return AuditTimelineEntry(
            event_id=record.event_id,
            runtime_id=runtime_id,
            event_type=record.event_type,
            entity_type=(
                self._optional_text(
                    record.entity_type
                )
            ),
            entity_id=(
                self._optional_text(
                    record.entity_id
                )
            ),
            message=message,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload_present=bool(
                record.payload
            ),
            occurred_at=record.occurred_at,
        )

    @classmethod
    def _extract_links(
        cls,
        payload: str | None,
    ) -> tuple[
        str | None,
        str | None,
    ]:
        """
        Parse only the existing checkpoint envelope linkage.

        The nested opaque payload itself is deliberately ignored.
        """

        if payload is None:
            return (
                None,
                None,
            )

        if not isinstance(
            payload,
            str,
        ):
            return (
                None,
                None,
            )

        try:
            decoded = json.loads(
                payload
            )

        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            return (
                None,
                None,
            )

        if not isinstance(
            decoded,
            dict,
        ):
            return (
                None,
                None,
            )

        return (
            cls._optional_text(
                decoded.get(
                    "correlation_id"
                )
            ),
            cls._optional_text(
                decoded.get(
                    "causation_id"
                )
            ),
        )

    @staticmethod
    def _optional_text(
        value: object,
        *,
        limit: int = 250,
    ) -> str | None:
        if value is None:
            return None

        if not isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        ):
            return None

        normalized = str(
            value
        ).strip()

        if not normalized:
            return None

        return normalized[:limit]

    @staticmethod
    def _normalize_runtime_id(
        runtime_id: str,
    ) -> str:
        if not isinstance(
            runtime_id,
            str,
        ):
            raise TypeError(
                "runtime_id must be str"
            )

        normalized = runtime_id.strip()

        if not normalized:
            raise ValueError(
                "runtime_id cannot be empty"
            )

        return normalized


__all__ = [
    "AuditTimelineIntegrityError",
    "AuditTimelineService",
]
