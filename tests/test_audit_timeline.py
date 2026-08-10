from datetime import datetime

import pytest

from src.database.schema import (
    AuditEventRecord,
)
from src.reporting.audit_timeline import (
    AuditTimelineIntegrityError,
    AuditTimelineService,
)


NOW = datetime(
    2026,
    8,
    10,
    9,
    30,
)

LATER = datetime(
    2026,
    8,
    10,
    10,
    0,
)


def audit(
    *,
    event_id: str,
    occurred_at: datetime,
    runtime_id: str = "RUNTIME-001",
    payload: str | None = None,
) -> AuditEventRecord:
    return AuditEventRecord(
        event_id=event_id,
        runtime_id=runtime_id,
        event_type="POSITION_OPENED",
        entity_type="POSITION",
        entity_id="POS-001",
        message=None,
        payload=payload,
        occurred_at=occurred_at,
    )


class FakeAuditRepository:
    def __init__(
        self,
        records: tuple[
            AuditEventRecord,
            ...,
        ],
    ) -> None:
        self.records = records

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        AuditEventRecord,
        ...,
    ]:
        return tuple(
            record
            for record in self.records
            if record.runtime_id == runtime_id
        )


def test_timeline_extracts_links_but_not_opaque_payload():
    repository = FakeAuditRepository(
        (
            audit(
                event_id="EVENT-001",
                occurred_at=NOW,
                payload=(
                    '{"correlation_id":"CORR-1",'
                    '"causation_id":"CAUSE-1",'
                    '"payload":{"access_token":'
                    '"DO-NOT-EXPOSE"}}'
                ),
            ),
        )
    )

    service = AuditTimelineService(
        audit_repository=repository
    )

    entry = service.list_runtime(
        "RUNTIME-001"
    )[0]

    assert entry.correlation_id == "CORR-1"
    assert entry.causation_id == "CAUSE-1"

    assert entry.payload_present is True

    # No raw payload field exists in the M12 read model.
    assert (
        "DO-NOT-EXPOSE"
        not in repr(
            entry
        )
    )


def test_malformed_payload_does_not_break_timeline():
    repository = FakeAuditRepository(
        (
            audit(
                event_id="EVENT-001",
                occurred_at=NOW,
                payload="{not-json",
            ),
        )
    )

    entry = AuditTimelineService(
        audit_repository=repository
    ).list_runtime(
        "RUNTIME-001"
    )[0]

    assert entry.correlation_id is None
    assert entry.causation_id is None
    assert entry.payload_present is True


def test_timeline_is_deterministically_sorted():
    repository = FakeAuditRepository(
        (
            audit(
                event_id="EVENT-002",
                occurred_at=LATER,
            ),
            audit(
                event_id="EVENT-001",
                occurred_at=NOW,
            ),
        )
    )

    entries = AuditTimelineService(
        audit_repository=repository
    ).list_runtime(
        "RUNTIME-001"
    )

    assert [
        entry.event_id
        for entry in entries
    ] == [
        "EVENT-001",
        "EVENT-002",
    ]


def test_runtime_identity_mismatch_fails_closed():
    class BadRepository:
        def list_by_runtime(
            self,
            runtime_id: str,
        ) -> tuple[
            AuditEventRecord,
            ...,
        ]:
            del runtime_id

            return (
                audit(
                    event_id="EVENT-001",
                    occurred_at=NOW,
                    runtime_id="OTHER-RUNTIME",
                ),
            )

    with pytest.raises(
        AuditTimelineIntegrityError,
        match="runtime_id",
    ):
        AuditTimelineService(
            audit_repository=BadRepository()
        ).list_runtime(
            "RUNTIME-001"
        )
