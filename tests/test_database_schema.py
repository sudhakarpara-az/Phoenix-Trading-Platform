"""
Phoenix M08-T03 Persistent Database Schema tests.
"""

from datetime import (
    date,
    datetime,
)

import pytest

from sqlalchemy import (
    inspect,
    select,
)
from sqlalchemy.exc import (
    IntegrityError,
)

from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.schema import (
    AuditEventRecord,
    Base,
    OptionSelectionRecord,
    OrderFillRecord,
    OrderRecord,
    PnLSnapshotRecord,
    PositionRecord,
    RiskSnapshotRecord,
    RuntimeSessionRecord,
    SignalRecord,
    create_schema,
    drop_schema,
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


EXPECTED_TABLES = {
    # M08 Runtime / Trading persistence
    "runtime_sessions",
    "signals",
    "option_selections",
    "orders",
    "order_fills",
    "positions",
    "pnl_snapshots",
    "risk_snapshots",
    "audit_events",

    # M09 Broker / Account persistence
    "broker_accounts",
    "broker_sessions",
    "account_fund_snapshots",
    "broker_connectivity_snapshots",
    "account_health_snapshots",
    "account_eligibility_snapshots",
    "trading_control_states",

    # M15 Tenant / User / Account membership persistence
    "tenants",
    "users",
    "user_broker_account_memberships",
    "user_password_credentials",
}


def make_database():
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

    return (
        database,
        sessions,
    )


def add_runtime(
    session,
    *,
    runtime_id: str = "PHOENIX-TEST",
) -> RuntimeSessionRecord:
    record = RuntimeSessionRecord(
        runtime_id=runtime_id,
        trading_date=TODAY,
        mode="DRY_RUN",
        state="RUNNING",
        started_at=NOW,
        updated_at=NOW,
        recovery_required=False,
        recovered=False,
    )

    session.add(
        record
    )

    session.flush()

    return record


def add_signal(
    session,
    *,
    runtime_id: str = "PHOENIX-TEST",
    signal_id: str = "SIG-001",
) -> SignalRecord:
    record = SignalRecord(
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

    session.add(
        record
    )

    session.flush()

    return record


def add_entry_order(
    session,
    *,
    runtime_id: str = "PHOENIX-TEST",
    signal_id: str = "SIG-001",
    intent_id: str = "ORD-001",
) -> OrderRecord:
    record = OrderRecord(
        order_intent_id=intent_id,
        runtime_id=runtime_id,
        signal_id=signal_id,
        position_id=None,
        security_id="41009",
        symbol=(
            "NIFTY50-20260811-24450-CE"
        ),
        side="BUY",
        order_type="LIMIT",
        reason="ENTRY",
        quantity=65,
        limit_price=101,
        execution_mode="DRY_RUN",
        status="FILLED",
        broker_name="FAKE",
        broker_order_id="BROKER-001",
        filled_quantity=65,
        average_fill_price=100.65,
        created_at=NOW,
        submitted_at=NOW,
        updated_at=NOW,
    )

    session.add(
        record
    )

    session.flush()

    return record


def add_position(
    session,
    *,
    runtime_id: str = "PHOENIX-TEST",
    signal_id: str = "SIG-001",
    intent_id: str = "ORD-001",
) -> PositionRecord:
    record = PositionRecord(
        position_id="POS-001",
        risk_id="RISK:POS-001",
        runtime_id=runtime_id,
        signal_id=signal_id,
        entry_order_intent_id=intent_id,
        security_id="41009",
        symbol=(
            "NIFTY50-20260811-24450-CE"
        ),
        option_type="CALL",
        level="K5",
        original_quantity=65,
        open_quantity=65,
        closed_quantity=0,
        entry_price=100.65,
        realized_pnl=0,
        state="OPEN",
        stop_price=85.65,
        stop_risk_points=15,
        stop_state="ARMED",
        executable_target_price=None,
        mapped_target_price=None,
        booking_zone_start=None,
        booking_zone_end=None,
        target_state=None,
        opened_at=NOW,
        updated_at=NOW,
        closed_at=None,
    )

    session.add(
        record
    )

    session.flush()

    return record


# ============================================================
# Metadata / schema creation
# ============================================================


def test_metadata_contains_expected_tables() -> None:
    assert (
        set(Base.metadata.tables)
        == EXPECTED_TABLES
    )


def test_create_schema_creates_all_tables() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    create_schema(
        engine
    )

    inspector = inspect(
        engine
    )

    assert (
        set(inspector.get_table_names())
        == EXPECTED_TABLES
    )

    database.dispose()


def test_create_schema_is_idempotent() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    create_schema(engine)
    create_schema(engine)

    assert (
        set(
            inspect(
                engine
            ).get_table_names()
        )
        == EXPECTED_TABLES
    )

    database.dispose()


def test_drop_schema_removes_tables() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    create_schema(engine)

    drop_schema(engine)

    assert (
        inspect(
            engine
        ).get_table_names()
        == []
    )

    database.dispose()


# ============================================================
# Runtime
# ============================================================


def test_runtime_record_round_trip() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)

    with sessions.session_scope() as session:
        runtime = session.get(
            RuntimeSessionRecord,
            "PHOENIX-TEST",
        )

        assert runtime is not None
        assert runtime.mode == "DRY_RUN"
        assert runtime.state == "RUNNING"
        assert runtime.trading_date == TODAY

    sessions.stop()
    database.dispose()


def test_invalid_runtime_mode_rejected() -> None:
    database, sessions = (
        make_database()
    )

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            session.add(
                RuntimeSessionRecord(
                    runtime_id="INVALID",
                    trading_date=TODAY,
                    mode="MAGIC",
                    state="RUNNING",
                    started_at=NOW,
                    updated_at=NOW,
                    recovery_required=False,
                    recovered=False,
                )
            )

    sessions.stop()
    database.dispose()


def test_invalid_runtime_state_rejected() -> None:
    database, sessions = (
        make_database()
    )

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            session.add(
                RuntimeSessionRecord(
                    runtime_id="INVALID",
                    trading_date=TODAY,
                    mode="LIVE",
                    state="UNKNOWN",
                    started_at=NOW,
                    updated_at=NOW,
                    recovery_required=False,
                    recovered=False,
                )
            )

    sessions.stop()
    database.dispose()


# ============================================================
# Foreign key integrity
# ============================================================


def test_signal_requires_runtime() -> None:
    database, sessions = (
        make_database()
    )

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            add_signal(
                session,
                runtime_id="UNKNOWN",
            )

    sessions.stop()
    database.dispose()


def test_order_requires_runtime() -> None:
    database, sessions = (
        make_database()
    )

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            session.add(
                OrderRecord(
                    order_intent_id="ORD-001",
                    runtime_id="UNKNOWN",
                    signal_id=None,
                    position_id=None,
                    security_id="41009",
                    symbol="NIFTY-CE",
                    side="BUY",
                    order_type="LIMIT",
                    reason="ENTRY",
                    quantity=65,
                    limit_price=100,
                    execution_mode="DRY_RUN",
                    status="CREATED",
                    broker_name=None,
                    broker_order_id=None,
                    filled_quantity=0,
                    average_fill_price=None,
                    created_at=NOW,
                    submitted_at=None,
                    updated_at=NOW,
                )
            )

    sessions.stop()
    database.dispose()


# ============================================================
# Signal
# ============================================================


def test_signal_round_trip() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)

    with sessions.session_scope() as session:
        signal = session.get(
            SignalRecord,
            "SIG-001",
        )

        assert signal is not None
        assert signal.level == "K5"
        assert signal.option_type == "CALL"
        assert signal.quantity == 65

    sessions.stop()
    database.dispose()


def test_signal_zero_quantity_rejected() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            session.add(
                SignalRecord(
                    signal_id="SIG-BAD",
                    runtime_id="PHOENIX-TEST",
                    trading_date=TODAY,
                    level="K5",
                    signal_type="BUY_CALL",
                    option_type="CALL",
                    underlying_price=24600,
                    quantity=0,
                    status="CREATED",
                    reason=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

    sessions.stop()
    database.dispose()


# ============================================================
# Option Selection
# ============================================================


def test_option_selection_round_trip() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)

    with sessions.session_scope() as session:
        session.add(
            OptionSelectionRecord(
                selection_id="SEL-001",
                runtime_id="PHOENIX-TEST",
                signal_id="SIG-001",
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-"
                    "24450-CE"
                ),
                security_id="41009",
                option_type="CALL",
                strike=24450,
                expiry=date(
                    2026,
                    8,
                    11,
                ),
                lot_size=65,
                ltp=205,
                delta=0.66844,
                target_delta=0.64,
                bid=204.4,
                ask=204.9,
                volume=21531250,
                open_interest=764465,
                quote_received_at=NOW,
                selected_at=NOW,
            )
        )

    with sessions.session_scope() as session:
        selection = session.get(
            OptionSelectionRecord,
            "SEL-001",
        )

        assert selection is not None
        assert selection.security_id == "41009"
        assert selection.delta == pytest.approx(
            0.66844
        )
        assert selection.lot_size == 65

    sessions.stop()
    database.dispose()


def test_only_one_selection_per_signal() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)

    def record(
        selection_id,
    ):
        return OptionSelectionRecord(
            selection_id=selection_id,
            runtime_id="PHOENIX-TEST",
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
            bid=None,
            ask=None,
            volume=None,
            open_interest=None,
            quote_received_at=NOW,
            selected_at=NOW,
        )

    with sessions.session_scope() as session:
        session.add(
            record(
                "SEL-001"
            )
        )

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            session.add(
                record(
                    "SEL-002"
                )
            )

    sessions.stop()
    database.dispose()


# ============================================================
# Orders / fills
# ============================================================


def test_order_round_trip() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)
        add_entry_order(session)

    with sessions.session_scope() as session:
        order = session.get(
            OrderRecord,
            "ORD-001",
        )

        assert order is not None
        assert order.side == "BUY"
        assert order.quantity == 65
        assert order.filled_quantity == 65

        assert order.average_fill_price == (
            pytest.approx(
                100.65
            )
        )

    sessions.stop()
    database.dispose()


def test_order_overfill_rejected() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            session.add(
                OrderRecord(
                    order_intent_id="ORD-BAD",
                    runtime_id="PHOENIX-TEST",
                    signal_id=None,
                    position_id=None,
                    security_id="41009",
                    symbol="NIFTY-CE",
                    side="BUY",
                    order_type="LIMIT",
                    reason="ENTRY",
                    quantity=65,
                    limit_price=100,
                    execution_mode="DRY_RUN",
                    status="FILLED",
                    broker_name="FAKE",
                    broker_order_id="B1",
                    filled_quantity=66,
                    average_fill_price=100,
                    created_at=NOW,
                    submitted_at=NOW,
                    updated_at=NOW,
                )
            )

    sessions.stop()
    database.dispose()


def test_multiple_fills_per_order() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)
        add_entry_order(session)

    with sessions.session_scope() as session:
        session.add_all(
            [
                OrderFillRecord(
                    fill_id="FILL-001",
                    order_intent_id="ORD-001",
                    broker_trade_id="TRADE-1",
                    quantity=30,
                    price=100.5,
                    filled_at=NOW,
                ),
                OrderFillRecord(
                    fill_id="FILL-002",
                    order_intent_id="ORD-001",
                    broker_trade_id="TRADE-2",
                    quantity=35,
                    price=100.78,
                    filled_at=NOW,
                ),
            ]
        )

    with sessions.session_scope() as session:
        fills = session.scalars(
            select(
                OrderFillRecord
            ).where(
                OrderFillRecord
                .order_intent_id
                == "ORD-001"
            )
        ).all()

        assert len(fills) == 2

        assert sum(
            fill.quantity
            for fill in fills
        ) == 65

    sessions.stop()
    database.dispose()


# ============================================================
# Position
# ============================================================


def test_position_round_trip() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)
        add_entry_order(session)
        add_position(session)

    with sessions.session_scope() as session:
        position = session.get(
            PositionRecord,
            "POS-001",
        )

        assert position is not None

        assert (
            position.risk_id
            == "RISK:POS-001"
        )

        assert position.open_quantity == 65
        assert position.closed_quantity == 0

        assert position.entry_price == (
            pytest.approx(
                100.65
            )
        )

        assert position.stop_price == (
            pytest.approx(
                85.65
            )
        )

    sessions.stop()
    database.dispose()


def test_position_quantity_conservation_enforced() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)
        add_entry_order(session)

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            bad = add_position(
                session
            )

            bad.open_quantity = 60
            bad.closed_quantity = 1

    session.flush()
    sessions.stop()
    database.dispose()


def test_duplicate_risk_id_rejected() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)
        add_entry_order(session)
        add_position(session)

    with sessions.session_scope() as session:
        add_signal(
            session,
            signal_id="SIG-002",
        )

        add_entry_order(
            session,
            signal_id="SIG-002",
            intent_id="ORD-002",
        )

    with pytest.raises(
        IntegrityError
    ):
        with sessions.session_scope() as session:
            position = PositionRecord(
                position_id="POS-002",
                risk_id="RISK:POS-001",
                runtime_id="PHOENIX-TEST",
                signal_id="SIG-002",
                entry_order_intent_id="ORD-002",
                security_id="41019",
                symbol="NIFTY-PE",
                option_type="PUT",
                level="K7",
                original_quantity=65,
                open_quantity=65,
                closed_quantity=0,
                entry_price=100,
                realized_pnl=0,
                state="OPEN",
                stop_price=85,
                stop_risk_points=15,
                stop_state="ARMED",
                executable_target_price=None,
                mapped_target_price=None,
                booking_zone_start=None,
                booking_zone_end=None,
                target_state=None,
                opened_at=NOW,
                updated_at=NOW,
                closed_at=None,
            )

            session.add(
                position
            )

    sessions.stop()
    database.dispose()


# ============================================================
# P&L
# ============================================================


def test_pnl_snapshot_round_trip() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)
        add_entry_order(session)
        add_position(session)

    with sessions.session_scope() as session:
        session.add(
            PnLSnapshotRecord(
                snapshot_id="PNL-001",
                runtime_id="PHOENIX-TEST",
                position_id="POS-001",
                realized_pnl=780,
                unrealized_pnl=525,
                total_pnl=1305,
                unrealized_points=15,
                ltp=115,
                open_quantity=35,
                captured_at=NOW,
            )
        )

    with sessions.session_scope() as session:
        snapshot = session.get(
            PnLSnapshotRecord,
            "PNL-001",
        )

        assert snapshot is not None
        assert snapshot.total_pnl == 1305
        assert snapshot.open_quantity == 35

    sessions.stop()
    database.dispose()


# ============================================================
# Risk
# ============================================================


def test_risk_snapshot_round_trip() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)

        session.add(
            RiskSnapshotRecord(
                snapshot_id="RISK-SNAP-001",
                runtime_id="PHOENIX-TEST",
                trading_date=TODAY,
                realized_pnl=1000,
                unrealized_pnl=500,
                total_pnl=1500,
                open_positions=1,
                closed_positions=1,
                open_quantity=65,
                new_entries_allowed=True,
                lock_reason="NONE",
                captured_at=NOW,
            )
        )

    with sessions.session_scope() as session:
        snapshot = session.get(
            RiskSnapshotRecord,
            "RISK-SNAP-001",
        )

        assert snapshot is not None
        assert snapshot.total_pnl == 1500

        assert (
            snapshot.new_entries_allowed
            is True
        )

    sessions.stop()
    database.dispose()


# ============================================================
# Audit
# ============================================================


def test_audit_event_round_trip() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)

        session.add(
            AuditEventRecord(
                event_id="EVENT-001",
                runtime_id="PHOENIX-TEST",
                event_type="RUNTIME_STARTED",
                entity_type="RUNTIME",
                entity_id="PHOENIX-TEST",
                message=(
                    "Phoenix runtime started"
                ),
                payload=None,
                occurred_at=NOW,
            )
        )

    with sessions.session_scope() as session:
        event = session.get(
            AuditEventRecord,
            "EVENT-001",
        )

        assert event is not None

        assert (
            event.event_type
            == "RUNTIME_STARTED"
        )

    sessions.stop()
    database.dispose()


# ============================================================
# Cascades / integrity
# ============================================================


def test_runtime_delete_cascades_signal() -> None:
    database, sessions = (
        make_database()
    )

    with sessions.session_scope() as session:
        add_runtime(session)
        add_signal(session)

    with sessions.session_scope() as session:
        runtime = session.get(
            RuntimeSessionRecord,
            "PHOENIX-TEST",
        )

        assert runtime is not None

        session.delete(
            runtime
        )

    with sessions.session_scope() as session:
        signal = session.get(
            SignalRecord,
            "SIG-001",
        )

        assert signal is None

    sessions.stop()
    database.dispose()
