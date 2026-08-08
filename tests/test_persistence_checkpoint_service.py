"""
Phoenix M08-T07 Persistence Integration /
State Checkpointing tests.
"""

from datetime import (
    date,
    datetime,
    timedelta,
)
import json

import pytest

from src.database.checkpoint_service import (
    PersistenceCheckpointError,
    RuntimeEventAuditSubscriber,
    SQLAlchemyCheckpointService,
)
from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyAuditEventRepository,
    SQLAlchemyRuntimeSessionRepository,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.database.schema import (
    create_schema,
)
from src.database.session import (
    DatabaseSessionManager,
)
from src.runtime.runtime_events import (
    RuntimeEvent,
    RuntimeEventType,
)
from src.runtime.runtime_types import (
    RuntimeFailure,
    RuntimeFailureCode,
    RuntimeId,
    RuntimeMode,
    RuntimeSnapshot,
    RuntimeState,
)


TRADING_DATE = date(
    2026,
    8,
    8,
)

CREATED_AT = datetime(
    2026,
    8,
    8,
    8,
    45,
)

STARTED_AT = datetime(
    2026,
    8,
    8,
    9,
    0,
)

RUNNING_AT = datetime(
    2026,
    8,
    8,
    9,
    20,
)

LATER = (
    RUNNING_AT
    + timedelta(seconds=1)
)

RUNTIME_ID = RuntimeId(
    "PHOENIX:2026-08-08:TEST"
)


def make_runtime():
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    create_schema(
        engine
    )

    sessions = DatabaseSessionManager(
        database_engine=database
    )

    sessions.start()

    runtime_repo = (
        SQLAlchemyRuntimeSessionRepository(
            sessions=sessions
        )
    )

    audit_repo = (
        SQLAlchemyAuditEventRepository(
            sessions=sessions
        )
    )

    service = (
        SQLAlchemyCheckpointService(
            runtime_repository=(
                runtime_repo
            ),
            audit_repository=(
                audit_repo
            ),
        )
    )

    return (
        database,
        sessions,
        runtime_repo,
        audit_repo,
        service,
    )


def created_snapshot() -> RuntimeSnapshot:
    return RuntimeSnapshot(
        runtime_id=RUNTIME_ID,
        trading_date=TRADING_DATE,
        mode=RuntimeMode.DRY_RUN,
        state=RuntimeState.CREATED,
        started_at=None,
        updated_at=CREATED_AT,
    )


def running_snapshot() -> RuntimeSnapshot:
    return RuntimeSnapshot(
        runtime_id=RUNTIME_ID,
        trading_date=TRADING_DATE,
        mode=RuntimeMode.DRY_RUN,
        state=RuntimeState.RUNNING,
        started_at=STARTED_AT,
        updated_at=RUNNING_AT,
    )


# ============================================================
# Runtime checkpoint
# ============================================================


def test_first_runtime_checkpoint_inserts() -> None:
    (
        database,
        sessions,
        runtime_repo,
        _,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        created_snapshot()
    )

    record = runtime_repo.require(
        RUNTIME_ID.value
    )

    assert record.runtime_id == (
        RUNTIME_ID.value
    )

    assert record.state == "CREATED"
    assert record.mode == "DRY_RUN"

    sessions.stop()
    database.dispose()


def test_runtime_exists_after_checkpoint() -> None:
    (
        database,
        sessions,
        _,
        _,
        service,
    ) = make_runtime()

    assert (
        service.runtime_exists(
            RUNTIME_ID.value
        )
        is False
    )

    service.checkpoint_runtime(
        created_snapshot()
    )

    assert (
        service.runtime_exists(
            RUNTIME_ID.value
        )
        is True
    )

    sessions.stop()
    database.dispose()


def test_second_runtime_checkpoint_updates() -> None:
    (
        database,
        sessions,
        runtime_repo,
        _,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        created_snapshot()
    )

    service.checkpoint_runtime(
        running_snapshot()
    )

    record = runtime_repo.require(
        RUNTIME_ID.value
    )

    assert record.state == "RUNNING"

    assert (
        record.started_at
        == STARTED_AT
    )

    assert (
        record.updated_at
        == RUNNING_AT
    )

    sessions.stop()
    database.dispose()


def test_runtime_checkpoint_preserves_live_mode() -> None:
    (
        database,
        sessions,
        runtime_repo,
        _,
        service,
    ) = make_runtime()

    snapshot = RuntimeSnapshot(
        runtime_id=RUNTIME_ID,
        trading_date=TRADING_DATE,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.RUNNING,
        started_at=STARTED_AT,
        updated_at=RUNNING_AT,
    )

    service.checkpoint_runtime(
        snapshot
    )

    record = runtime_repo.require(
        RUNTIME_ID.value
    )

    assert record.mode == "LIVE"

    sessions.stop()
    database.dispose()


def test_runtime_failure_is_persisted() -> None:
    (
        database,
        sessions,
        runtime_repo,
        _,
        service,
    ) = make_runtime()

    failure = RuntimeFailure(
        code=(
            RuntimeFailureCode
            .DATABASE_FAILED
        ),
        message="database unavailable",
        occurred_at=RUNNING_AT,
        recoverable=True,
        component="database",
    )

    snapshot = RuntimeSnapshot(
        runtime_id=RUNTIME_ID,
        trading_date=TRADING_DATE,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.FAILED,
        started_at=STARTED_AT,
        updated_at=RUNNING_AT,
        failure=failure,
        recovery_required=True,
    )

    service.checkpoint_runtime(
        snapshot
    )

    record = runtime_repo.require(
        RUNTIME_ID.value
    )

    assert record.state == "FAILED"

    assert (
        record.failure_code
        == "DATABASE_FAILED"
    )

    assert (
        record.failure_message
        == "database unavailable"
    )

    assert (
        record.failure_component
        == "database"
    )

    assert (
        record.failure_recoverable
        is True
    )

    assert (
        record.recovery_required
        is True
    )

    sessions.stop()
    database.dispose()


def test_recovery_flags_are_persisted() -> None:
    (
        database,
        sessions,
        runtime_repo,
        _,
        service,
    ) = make_runtime()

    snapshot = RuntimeSnapshot(
        runtime_id=RUNTIME_ID,
        trading_date=TRADING_DATE,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.RECOVERING,
        started_at=STARTED_AT,
        updated_at=RUNNING_AT,
        recovery_required=True,
        recovered=False,
    )

    service.checkpoint_runtime(
        snapshot
    )

    record = runtime_repo.require(
        RUNTIME_ID.value
    )

    assert (
        record.recovery_required
        is True
    )

    assert record.recovered is False

    sessions.stop()
    database.dispose()


# ============================================================
# Event checkpoint
# ============================================================


def test_event_checkpoint_creates_audit_record() -> None:
    (
        database,
        sessions,
        _,
        audit_repo,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    event = RuntimeEvent(
        event_id="EVENT-001",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .SIGNAL_CREATED
        ),
        occurred_at=RUNNING_AT,
        payload=None,
    )

    service.checkpoint_event(
        event
    )

    record = audit_repo.require(
        "EVENT-001"
    )

    assert (
        record.event_type
        == "SIGNAL_CREATED"
    )

    assert (
        record.runtime_id
        == RUNTIME_ID.value
    )

    assert (
        record.occurred_at
        == RUNNING_AT
    )

    sessions.stop()
    database.dispose()


def test_event_id_is_preserved() -> None:
    (
        database,
        sessions,
        _,
        audit_repo,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    event = RuntimeEvent(
        event_id="EVENT-EXACT",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .POSITION_OPENED
        ),
        occurred_at=RUNNING_AT,
    )

    service.checkpoint_event(
        event
    )

    assert (
        audit_repo.require(
            "EVENT-EXACT"
        ).event_id
        == "EVENT-EXACT"
    )

    sessions.stop()
    database.dispose()


def test_event_payload_serialized() -> None:
    (
        database,
        sessions,
        _,
        audit_repo,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    event = RuntimeEvent(
        event_id="EVENT-001",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .POSITION_OPENED
        ),
        occurred_at=RUNNING_AT,
        payload={
            "position_id": "POS-001",
            "quantity": 65,
        },
        correlation_id="TRADE-001",
        causation_id="EVENT-PREVIOUS",
    )

    service.checkpoint_event(
        event
    )

    record = audit_repo.require(
        "EVENT-001"
    )

    assert record.payload is not None

    payload = json.loads(
        record.payload
    )

    assert payload[
        "correlation_id"
    ] == "TRADE-001"

    assert payload[
        "causation_id"
    ] == "EVENT-PREVIOUS"

    assert payload[
        "payload"
    ][
        "position_id"
    ] == "POS-001"

    assert payload[
        "payload"
    ][
        "quantity"
    ] == 65

    sessions.stop()
    database.dispose()


def test_event_entity_metadata_extracted() -> None:
    (
        database,
        sessions,
        _,
        audit_repo,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    event = RuntimeEvent(
        event_id="EVENT-ENTITY",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .POSITION_UPDATED
        ),
        occurred_at=RUNNING_AT,
        payload={
            "entity_type": "POSITION",
            "entity_id": "POS-001",
            "open_quantity": 35,
        },
    )

    service.checkpoint_event(
        event
    )

    record = audit_repo.require(
        "EVENT-ENTITY"
    )

    assert (
        record.entity_type
        == "POSITION"
    )

    assert (
        record.entity_id
        == "POS-001"
    )

    sessions.stop()
    database.dispose()


def test_event_without_entity_metadata_allowed() -> None:
    (
        database,
        sessions,
        _,
        audit_repo,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    event = RuntimeEvent(
        event_id="EVENT-NO-ENTITY",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .RUNTIME_READY
        ),
        occurred_at=RUNNING_AT,
    )

    service.checkpoint_event(
        event
    )

    record = audit_repo.require(
        "EVENT-NO-ENTITY"
    )

    assert record.entity_type is None
    assert record.entity_id is None

    sessions.stop()
    database.dispose()


def test_datetime_payload_serialized() -> None:
    (
        database,
        sessions,
        _,
        audit_repo,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    event = RuntimeEvent(
        event_id="EVENT-DATE",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .PNL_UPDATED
        ),
        occurred_at=RUNNING_AT,
        payload={
            "captured_at": LATER,
        },
    )

    service.checkpoint_event(
        event
    )

    record = audit_repo.require(
        "EVENT-DATE"
    )

    payload = json.loads(
        record.payload
    )

    assert (
        payload["payload"][
            "captured_at"
        ]
        == LATER.isoformat()
    )

    sessions.stop()
    database.dispose()


# ============================================================
# Foreign key protection
# ============================================================


def test_event_requires_persisted_runtime() -> None:
    (
        database,
        sessions,
        _,
        _,
        service,
    ) = make_runtime()

    event = RuntimeEvent(
        event_id="EVENT-001",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .SIGNAL_CREATED
        ),
        occurred_at=RUNNING_AT,
    )

    with pytest.raises(
        PersistenceCheckpointError,
        match=(
            "runtime event checkpoint failed"
        ),
    ):
        service.checkpoint_event(
            event
        )

    sessions.stop()
    database.dispose()


# ============================================================
# Duplicate event protection
# ============================================================


def test_duplicate_event_checkpoint_rejected() -> None:
    (
        database,
        sessions,
        _,
        _,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    event = RuntimeEvent(
        event_id="EVENT-DUPLICATE",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .SIGNAL_CREATED
        ),
        occurred_at=RUNNING_AT,
    )

    service.checkpoint_event(
        event
    )

    with pytest.raises(
        PersistenceCheckpointError,
        match=(
            "runtime event checkpoint failed"
        ),
    ):
        service.checkpoint_event(
            event
        )

    sessions.stop()
    database.dispose()

def test_event_bus_can_persist_event_through_subscriber() -> None:
    (
        database,
        sessions,
        _,
        audit_repo,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    bus = RuntimeEventBus()

    subscriber = (
        RuntimeEventAuditSubscriber(
            checkpoint_service=service
        )
    )

    bus.subscribe(
        RuntimeEventType.SIGNAL_CREATED,
        subscriber,
    )

    event = RuntimeEvent(
        event_id="EVENT-BUS-001",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .SIGNAL_CREATED
        ),
        occurred_at=RUNNING_AT,
        payload={
            "signal_id": "SIG-001"
        },
    )

    result = bus.publish(
        event
    )

    assert result.successful is True
    assert result.delivered_count == 1

    stored = audit_repo.require(
        "EVENT-BUS-001"
    )

    assert (
        stored.event_type
        == "SIGNAL_CREATED"
    )

    sessions.stop()
    database.dispose()    
def test_audit_subscriber_can_subscribe_all_events() -> None:
    (
        database,
        sessions,
        _,
        audit_repo,
        service,
    ) = make_runtime()

    service.checkpoint_runtime(
        running_snapshot()
    )

    bus = RuntimeEventBus()

    subscriber = (
        RuntimeEventAuditSubscriber(
            checkpoint_service=service
        )
    )

    subscriber.subscribe_all(
        bus
    )

    for event_type in RuntimeEventType:
        assert (
            bus.subscriber_count(
                event_type
            )
            == 1
        )

    event = RuntimeEvent(
        event_id="EVENT-ALL-001",
        runtime_id=RUNTIME_ID,
        event_type=(
            RuntimeEventType
            .RISK_UPDATED
        ),
        occurred_at=RUNNING_AT,
    )

    bus.publish(
        event
    )

    assert (
        audit_repo.require(
            "EVENT-ALL-001"
        ).event_type
        == "RISK_UPDATED"
    )

    sessions.stop()
    database.dispose()    