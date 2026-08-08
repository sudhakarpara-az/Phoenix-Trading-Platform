"""
Phoenix M08-T04 Repository tests.
"""

from datetime import (
    date,
    datetime,
    timedelta,
)

import pytest

from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.repositories.sqlalchemy_repositories import (
    DuplicateRepositoryRecordError,
    RepositoryRecordNotFoundError,
    SQLAlchemyAuditEventRepository,
    SQLAlchemyOptionSelectionRepository,
    SQLAlchemyOrderFillRepository,
    SQLAlchemyOrderRepository,
    SQLAlchemyPnLSnapshotRepository,
    SQLAlchemyPositionRepository,
    SQLAlchemyRiskSnapshotRepository,
    SQLAlchemyRuntimeSessionRepository,
    SQLAlchemySignalRepository,
)
from src.database.schema import (
    AuditEventRecord,
    OptionSelectionRecord,
    OrderFillRecord,
    OrderRecord,
    PnLSnapshotRecord,
    PositionRecord,
    RiskSnapshotRecord,
    RuntimeSessionRecord,
    SignalRecord,
    create_schema,
)
from src.database.session import (
    DatabaseSessionManager,
)


TODAY = date(
    2026,
    8,
    8,
)

NOW = datetime(
    2026,
    8,
    8,
    10,
    0,
)

LATER = (
    NOW
    + timedelta(minutes=1)
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

    return database, sessions


def runtime_record(
    *,
    runtime_id: str = "RUNTIME-001",
    updated_at: datetime = NOW,
) -> RuntimeSessionRecord:
    return RuntimeSessionRecord(
        runtime_id=runtime_id,
        trading_date=TODAY,
        mode="DRY_RUN",
        state="RUNNING",
        started_at=NOW,
        updated_at=updated_at,
        recovery_required=False,
        recovered=False,
    )


def signal_record(
    *,
    signal_id: str = "SIG-001",
    runtime_id: str = "RUNTIME-001",
) -> SignalRecord:
    return SignalRecord(
        signal_id=signal_id,
        runtime_id=runtime_id,
        trading_date=TODAY,
        level="K5",
        signal_type="BUY_CALL",
        option_type="CALL",
        underlying_price=24600,
        quantity=65,
        status="CREATED",
        reason="K5 trigger",
        created_at=NOW,
        updated_at=NOW,
    )


def order_record(
    *,
    order_id: str = "ORD-001",
    runtime_id: str = "RUNTIME-001",
    signal_id: str | None = "SIG-001",
    status: str = "SUBMITTED",
    broker_order_id: str | None = "BROKER-001",
) -> OrderRecord:
    return OrderRecord(
        order_intent_id=order_id,
        runtime_id=runtime_id,
        signal_id=signal_id,
        position_id=None,
        security_id="41009",
        symbol="NIFTY-CE",
        side="BUY",
        order_type="LIMIT",
        reason="ENTRY",
        quantity=65,
        limit_price=101,
        execution_mode="DRY_RUN",
        status=status,
        broker_name="FAKE",
        broker_order_id=broker_order_id,
        filled_quantity=0,
        average_fill_price=None,
        created_at=NOW,
        submitted_at=NOW,
        updated_at=NOW,
    )


def position_record(
    *,
    position_id: str = "POS-001",
    state: str = "OPEN",
    open_quantity: int = 65,
    closed_quantity: int = 0,
) -> PositionRecord:
    return PositionRecord(
        position_id=position_id,
        risk_id=f"RISK:{position_id}",
        runtime_id="RUNTIME-001",
        signal_id="SIG-001",
        entry_order_intent_id="ORD-001",
        security_id="41009",
        symbol="NIFTY-CE",
        option_type="CALL",
        level="K5",
        original_quantity=65,
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        entry_price=100,
        realized_pnl=0,
        state=state,
        stop_price=85,
        stop_risk_points=15,
        stop_state="ARMED",
        executable_target_price=126,
        mapped_target_price=129,
        booking_zone_start=126,
        booking_zone_end=129,
        target_state="ARMED",
        opened_at=NOW,
        updated_at=NOW,
        closed_at=(
            NOW
            if open_quantity == 0
            else None
        ),
    )


def seed_entry_dependencies(
    runtime_repo,
    signal_repo,
    order_repo,
):
    runtime_repo.add(
        runtime_record()
    )

    signal_repo.add(
        signal_record()
    )

    order_repo.add(
        order_record(
            status="FILLED"
        )
    )


# ============================================================
# Base repository
# ============================================================


def test_repository_add_and_get() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    repo.add(
        runtime_record()
    )

    stored = repo.get(
        "RUNTIME-001"
    )

    assert stored is not None
    assert stored.runtime_id == "RUNTIME-001"

    sessions.stop()
    database.dispose()


def test_repository_require() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    repo.add(
        runtime_record()
    )

    stored = repo.require(
        "RUNTIME-001"
    )

    assert stored.runtime_id == "RUNTIME-001"

    sessions.stop()
    database.dispose()


def test_repository_require_missing_raises() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    with pytest.raises(
        RepositoryRecordNotFoundError
    ):
        repo.require(
            "MISSING"
        )

    sessions.stop()
    database.dispose()


def test_duplicate_add_rejected() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    repo.add(
        runtime_record()
    )

    with pytest.raises(
        DuplicateRepositoryRecordError
    ):
        repo.add(
            runtime_record()
        )

    sessions.stop()
    database.dispose()


def test_repository_delete() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    repo.add(
        runtime_record()
    )

    assert repo.delete(
        "RUNTIME-001"
    ) is True

    assert repo.get(
        "RUNTIME-001"
    ) is None

    sessions.stop()
    database.dispose()


def test_delete_missing_returns_false() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    assert repo.delete(
        "MISSING"
    ) is False

    sessions.stop()
    database.dispose()


def test_repository_update() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    record = runtime_record()

    repo.add(
        record
    )

    record.state = "STOPPING"
    record.updated_at = LATER

    updated = repo.update(
        record
    )

    assert updated.state == "STOPPING"

    persisted = repo.require(
        "RUNTIME-001"
    )

    assert persisted.state == "STOPPING"

    sessions.stop()
    database.dispose()


# ============================================================
# Runtime repository
# ============================================================


def test_runtime_latest() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    repo.add(
        runtime_record(
            runtime_id="RUNTIME-001",
            updated_at=NOW,
        )
    )

    repo.add(
        runtime_record(
            runtime_id="RUNTIME-002",
            updated_at=LATER,
        )
    )

    latest = repo.latest()

    assert latest is not None

    assert (
        latest.runtime_id
        == "RUNTIME-002"
    )

    sessions.stop()
    database.dispose()


def test_runtime_latest_for_date() -> None:
    database, sessions = make_runtime()

    repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    repo.add(
        runtime_record(
            runtime_id="RUNTIME-001",
            updated_at=NOW,
        )
    )

    repo.add(
        runtime_record(
            runtime_id="RUNTIME-002",
            updated_at=LATER,
        )
    )

    latest = (
        repo.latest_for_trading_date(
            TODAY
        )
    )

    assert latest is not None

    assert latest.runtime_id == "RUNTIME-002"

    sessions.stop()
    database.dispose()


# ============================================================
# Signal repository
# ============================================================


def test_signal_list_by_runtime() -> None:
    database, sessions = make_runtime()

    runtime_repo = (
        SQLAlchemyRuntimeSessionRepository(
            sessions=sessions
        )
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    runtime_repo.add(
        runtime_record()
    )

    signal_repo.add(
        signal_record(
            signal_id="SIG-001"
        )
    )

    signal_repo.add(
        signal_record(
            signal_id="SIG-002"
        )
    )

    signals = signal_repo.list_by_runtime(
        "RUNTIME-001"
    )

    assert len(signals) == 2

    sessions.stop()
    database.dispose()


# ============================================================
# Option selection repository
# ============================================================


def test_option_selection_get_by_signal() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    option_repo = SQLAlchemyOptionSelectionRepository(
        sessions=sessions
    )

    runtime_repo.add(
        runtime_record()
    )

    signal_repo.add(
        signal_record()
    )

    option_repo.add(
        OptionSelectionRecord(
            selection_id="SEL-001",
            runtime_id="RUNTIME-001",
            signal_id="SIG-001",
            underlying_symbol="NIFTY 50",
            symbol="NIFTY-CE",
            security_id="41009",
            option_type="CALL",
            strike=24450,
            expiry=date(
                2026,
                8,
                11,
            ),
            lot_size=65,
            ltp=100,
            delta=0.64,
            target_delta=0.64,
            bid=99.95,
            ask=100.05,
            volume=1000,
            open_interest=50000,
            quote_received_at=NOW,
            selected_at=NOW,
        )
    )

    selection = option_repo.get_by_signal(
        "SIG-001"
    )

    assert selection is not None
    assert selection.selection_id == "SEL-001"

    sessions.stop()
    database.dispose()


# ============================================================
# Order repository
# ============================================================


def test_order_list_open_orders() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    order_repo = SQLAlchemyOrderRepository(
        sessions=sessions
    )

    runtime_repo.add(
        runtime_record()
    )

    signal_repo.add(
        signal_record()
    )

    order_repo.add(
        order_record(
            order_id="ORD-OPEN",
            status="SUBMITTED",
            broker_order_id="BROKER-OPEN",
        )
    )

    order_repo.add(
        order_record(
            order_id="ORD-FILLED",
            status="FILLED",
            broker_order_id="BROKER-FILLED",
        )
    )

    open_orders = order_repo.list_open_orders(
        "RUNTIME-001"
    )

    assert len(open_orders) == 1

    assert (
        open_orders[0].order_intent_id
        == "ORD-OPEN"
    )

    sessions.stop()
    database.dispose()


def test_order_get_by_broker_id() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    order_repo = SQLAlchemyOrderRepository(
        sessions=sessions
    )

    runtime_repo.add(
        runtime_record()
    )

    signal_repo.add(
        signal_record()
    )

    order_repo.add(
        order_record()
    )

    stored = order_repo.get_by_broker_order_id(
        "BROKER-001"
    )

    assert stored is not None
    assert stored.order_intent_id == "ORD-001"

    sessions.stop()
    database.dispose()


# ============================================================
# Fill repository
# ============================================================


def test_fill_list_by_order() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    order_repo = SQLAlchemyOrderRepository(
        sessions=sessions
    )

    fill_repo = SQLAlchemyOrderFillRepository(
        sessions=sessions
    )

    seed_entry_dependencies(
        runtime_repo,
        signal_repo,
        order_repo,
    )

    fill_repo.add(
        OrderFillRecord(
            fill_id="FILL-001",
            order_intent_id="ORD-001",
            broker_trade_id="TRADE-001",
            quantity=30,
            price=100,
            filled_at=NOW,
        )
    )

    fill_repo.add(
        OrderFillRecord(
            fill_id="FILL-002",
            order_intent_id="ORD-001",
            broker_trade_id="TRADE-002",
            quantity=35,
            price=101,
            filled_at=LATER,
        )
    )

    fills = fill_repo.list_by_order(
        "ORD-001"
    )

    assert len(fills) == 2
    assert fills[0].fill_id == "FILL-001"
    assert fills[1].fill_id == "FILL-002"

    sessions.stop()
    database.dispose()


# ============================================================
# Position repository
# ============================================================


def test_position_list_open_positions() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    order_repo = SQLAlchemyOrderRepository(
        sessions=sessions
    )

    position_repo = SQLAlchemyPositionRepository(
        sessions=sessions
    )

    seed_entry_dependencies(
        runtime_repo,
        signal_repo,
        order_repo,
    )

    position_repo.add(
        position_record()
    )

    positions = (
        position_repo.list_open_positions(
            "RUNTIME-001"
        )
    )

    assert len(positions) == 1
    assert positions[0].open_quantity == 65

    sessions.stop()
    database.dispose()


def test_exit_pending_position_still_counts_as_open() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    order_repo = SQLAlchemyOrderRepository(
        sessions=sessions
    )

    position_repo = SQLAlchemyPositionRepository(
        sessions=sessions
    )

    seed_entry_dependencies(
        runtime_repo,
        signal_repo,
        order_repo,
    )

    position_repo.add(
        position_record(
            state="EXIT_PENDING"
        )
    )

    positions = (
        position_repo.list_open_positions(
            "RUNTIME-001"
        )
    )

    assert len(positions) == 1

    sessions.stop()
    database.dispose()


def test_closed_position_not_returned_as_open() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    order_repo = SQLAlchemyOrderRepository(
        sessions=sessions
    )

    position_repo = SQLAlchemyPositionRepository(
        sessions=sessions
    )

    seed_entry_dependencies(
        runtime_repo,
        signal_repo,
        order_repo,
    )

    position_repo.add(
        position_record(
            state="CLOSED",
            open_quantity=0,
            closed_quantity=65,
        )
    )

    positions = (
        position_repo.list_open_positions(
            "RUNTIME-001"
        )
    )

    assert positions == ()

    sessions.stop()
    database.dispose()


# ============================================================
# P&L repository
# ============================================================


def test_pnl_latest_for_position() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    signal_repo = SQLAlchemySignalRepository(
        sessions=sessions
    )

    order_repo = SQLAlchemyOrderRepository(
        sessions=sessions
    )

    position_repo = SQLAlchemyPositionRepository(
        sessions=sessions
    )

    pnl_repo = SQLAlchemyPnLSnapshotRepository(
        sessions=sessions
    )

    seed_entry_dependencies(
        runtime_repo,
        signal_repo,
        order_repo,
    )

    position_repo.add(
        position_record()
    )

    pnl_repo.add(
        PnLSnapshotRecord(
            snapshot_id="PNL-001",
            runtime_id="RUNTIME-001",
            position_id="POS-001",
            realized_pnl=0,
            unrealized_pnl=650,
            total_pnl=650,
            unrealized_points=10,
            ltp=110,
            open_quantity=65,
            captured_at=NOW,
        )
    )

    pnl_repo.add(
        PnLSnapshotRecord(
            snapshot_id="PNL-002",
            runtime_id="RUNTIME-001",
            position_id="POS-001",
            realized_pnl=0,
            unrealized_pnl=780,
            total_pnl=780,
            unrealized_points=12,
            ltp=112,
            open_quantity=65,
            captured_at=LATER,
        )
    )

    latest = pnl_repo.latest_for_position(
        "POS-001"
    )

    assert latest is not None
    assert latest.snapshot_id == "PNL-002"
    assert latest.total_pnl == 780

    sessions.stop()
    database.dispose()


# ============================================================
# Risk repository
# ============================================================


def test_risk_latest_for_runtime() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    risk_repo = SQLAlchemyRiskSnapshotRepository(
        sessions=sessions
    )

    runtime_repo.add(
        runtime_record()
    )

    risk_repo.add(
        RiskSnapshotRecord(
            snapshot_id="RISK-001",
            runtime_id="RUNTIME-001",
            trading_date=TODAY,
            realized_pnl=0,
            unrealized_pnl=500,
            total_pnl=500,
            open_positions=1,
            closed_positions=0,
            open_quantity=65,
            new_entries_allowed=True,
            lock_reason="NONE",
            captured_at=NOW,
        )
    )

    risk_repo.add(
        RiskSnapshotRecord(
            snapshot_id="RISK-002",
            runtime_id="RUNTIME-001",
            trading_date=TODAY,
            realized_pnl=1000,
            unrealized_pnl=0,
            total_pnl=1000,
            open_positions=0,
            closed_positions=1,
            open_quantity=0,
            new_entries_allowed=True,
            lock_reason="NONE",
            captured_at=LATER,
        )
    )

    latest = risk_repo.latest_for_runtime(
        "RUNTIME-001"
    )

    assert latest is not None
    assert latest.snapshot_id == "RISK-002"

    sessions.stop()
    database.dispose()


# ============================================================
# Audit repository
# ============================================================


def test_audit_list_by_runtime() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    audit_repo = SQLAlchemyAuditEventRepository(
        sessions=sessions
    )

    runtime_repo.add(
        runtime_record()
    )

    audit_repo.add(
        AuditEventRecord(
            event_id="EVENT-001",
            runtime_id="RUNTIME-001",
            event_type="RUNTIME_STARTED",
            entity_type="RUNTIME",
            entity_id="RUNTIME-001",
            message=None,
            payload=None,
            occurred_at=NOW,
        )
    )

    audit_repo.add(
        AuditEventRecord(
            event_id="EVENT-002",
            runtime_id="RUNTIME-001",
            event_type="SIGNAL_CREATED",
            entity_type="SIGNAL",
            entity_id="SIG-001",
            message=None,
            payload=None,
            occurred_at=LATER,
        )
    )

    events = audit_repo.list_by_runtime(
        "RUNTIME-001"
    )

    assert len(events) == 2

    sessions.stop()
    database.dispose()


def test_audit_list_by_entity() -> None:
    database, sessions = make_runtime()

    runtime_repo = SQLAlchemyRuntimeSessionRepository(
        sessions=sessions
    )

    audit_repo = SQLAlchemyAuditEventRepository(
        sessions=sessions
    )

    runtime_repo.add(
        runtime_record()
    )

    audit_repo.add(
        AuditEventRecord(
            event_id="EVENT-001",
            runtime_id="RUNTIME-001",
            event_type="POSITION_OPENED",
            entity_type="POSITION",
            entity_id="POS-001",
            message=None,
            payload=None,
            occurred_at=NOW,
        )
    )

    events = audit_repo.list_by_entity(
        entity_type="POSITION",
        entity_id="POS-001",
    )

    assert len(events) == 1

    assert (
        events[0].event_type
        == "POSITION_OPENED"
    )

    sessions.stop()
    database.dispose()