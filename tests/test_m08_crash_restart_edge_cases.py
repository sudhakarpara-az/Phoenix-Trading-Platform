"""
Phoenix M08-T11 Crash / Restart / Recovery Failure
& Edge-Case Tests.

Hardens the Runtime & Persistence Engine against:

    - process failure windows
    - persistence failures
    - unresolved BUY/SELL orders
    - partial broker fills
    - restart with open exposure
    - broker/database uncertainty
    - duplicate audit persistence
    - recovery restoration failures
    - illegal runtime transitions
    - premature new-entry enablement

No real broker orders are placed.
"""

from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    timedelta,
)
from types import SimpleNamespace

import pytest

from src.database.checkpoint_service import (
    PersistenceCheckpointError,
    SQLAlchemyCheckpointService,
)
from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyAuditEventRepository,
    SQLAlchemyOrderRepository,
    SQLAlchemyPositionRepository,
    SQLAlchemyRuntimeSessionRepository,
    SQLAlchemySignalRepository,
)
from src.database.schema import (
    OrderRecord,
    PositionRecord,
    RuntimeSessionRecord,
    SignalRecord,
    create_schema,
)
from src.database.session import (
    DatabaseSessionManager,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.recovery_types import (
    BrokerRecoveryOrderSnapshot,
    BrokerRecoveryOrderState,
    BrokerRecoveryPositionSnapshot,
    RecoveryIssueCode,
)
from src.runtime.runtime_events import (
    RuntimeEvent,
    RuntimeEventType,
)
from src.runtime.runtime_orchestrator import (
    RuntimeTransitionError,
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeFailureCode,
    RuntimeId,
    RuntimeMode,
    RuntimeSnapshot,
    RuntimeState,
)
from src.runtime.startup_recovery_service import (
    StartupRecoveryService,
)
from src.runtime.trading_pipeline import (
    TradingPipelineError,
    TradingRuntimePipeline,
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
    14,
    0,
)

LATER = (
    NOW
    + timedelta(seconds=1)
)

FORCE_EXIT_TIME = datetime(
    2026,
    8,
    8,
    15,
    15,
)


# ============================================================
# Persistence test runtime
# ============================================================


def make_database_runtime():
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

    signal_repo = (
        SQLAlchemySignalRepository(
            sessions=sessions
        )
    )

    order_repo = (
        SQLAlchemyOrderRepository(
            sessions=sessions
        )
    )

    position_repo = (
        SQLAlchemyPositionRepository(
            sessions=sessions
        )
    )

    audit_repo = (
        SQLAlchemyAuditEventRepository(
            sessions=sessions
        )
    )

    checkpoint = SQLAlchemyCheckpointService(
        runtime_repository=runtime_repo,
        audit_repository=audit_repo,
    )

    return {
        "database": database,
        "sessions": sessions,
        "runtime_repo": runtime_repo,
        "signal_repo": signal_repo,
        "order_repo": order_repo,
        "position_repo": position_repo,
        "audit_repo": audit_repo,
        "checkpoint": checkpoint,
    }


def close_database_runtime(
    runtime,
):
    runtime[
        "sessions"
    ].stop()

    runtime[
        "database"
    ].dispose()


def runtime_record(
    *,
    runtime_id="OLD-RUNTIME",
    state="RUNNING",
):
    return RuntimeSessionRecord(
        runtime_id=runtime_id,
        trading_date=TODAY,
        mode="LIVE",
        state=state,
        started_at=NOW,
        updated_at=NOW,
        stopped_at=(
            NOW
            if state == "STOPPED"
            else None
        ),
        recovery_required=(
            state != "STOPPED"
        ),
        recovered=False,
    )


def signal_record(
    *,
    runtime_id="OLD-RUNTIME",
):
    return SignalRecord(
        signal_id="SIG-001",
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


def unresolved_order_record(
    *,
    runtime_id="OLD-RUNTIME",
    order_id="ORD-001",
    broker_order_id="BROKER-001",
    side="BUY",
    status="SUBMITTED",
    filled_quantity=0,
):
    return OrderRecord(
        order_intent_id=order_id,
        runtime_id=runtime_id,
        signal_id="SIG-001",
        position_id=None,
        security_id="41009",
        symbol="NIFTY-CE",
        side=side,
        order_type=(
            "LIMIT"
            if side == "BUY"
            else "MARKET"
        ),
        reason=(
            "ENTRY"
            if side == "BUY"
            else "STOP_LOSS"
        ),
        quantity=65,
        limit_price=(
            101
            if side == "BUY"
            else None
        ),
        execution_mode="LIVE",
        status=status,
        broker_name="DHAN",
        broker_order_id=(
            broker_order_id
        ),
        filled_quantity=(
            filled_quantity
        ),
        average_fill_price=None,
        created_at=NOW,
        submitted_at=NOW,
        updated_at=NOW,
    )


def position_record(
    *,
    runtime_id="OLD-RUNTIME",
    position_id="POS-001",
    state="OPEN",
    open_quantity=65,
    closed_quantity=0,
    security_id="41009",
):
    return PositionRecord(
        position_id=position_id,
        risk_id=(
            f"RISK:{position_id}"
        ),
        runtime_id=runtime_id,
        signal_id="SIG-001",
        entry_order_intent_id="ORD-001",
        security_id=security_id,
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


def seed_runtime_signal_order(
    runtime,
    *,
    order=None,
):
    runtime[
        "runtime_repo"
    ].add(
        runtime_record()
    )

    runtime[
        "signal_repo"
    ].add(
        signal_record()
    )

    runtime[
        "order_repo"
    ].add(
        order
        or unresolved_order_record()
    )


# ============================================================
# Recovery fakes
# ============================================================


class FakeBrokerRecoveryProvider:
    def __init__(self):
        self.orders = {}
        self.positions = {}

        self.order_calls = []
        self.position_calls = []

    def get_order_snapshot(
        self,
        *,
        broker_order_id,
        checked_at,
    ):
        self.order_calls.append(
            (
                broker_order_id,
                checked_at,
            )
        )

        value = self.orders[
            broker_order_id
        ]

        if isinstance(
            value,
            Exception,
        ):
            raise value

        return value

    def get_position_snapshot(
        self,
        *,
        security_id,
        checked_at,
    ):
        self.position_calls.append(
            (
                security_id,
                checked_at,
            )
        )

        value = self.positions[
            security_id
        ]

        if isinstance(
            value,
            Exception,
        ):
            raise value

        return value


class FakeRecoveryRestorer:
    def __init__(
        self,
        *,
        fail_order=False,
        fail_position=False,
    ):
        self.fail_order = fail_order
        self.fail_position = fail_position

        self.orders = []
        self.positions = []

    def restore_order(
        self,
        *,
        persisted_order,
        broker_snapshot,
    ):
        if self.fail_order:
            raise RuntimeError(
                "order restore failed"
            )

        self.orders.append(
            (
                persisted_order,
                broker_snapshot,
            )
        )

    def restore_position(
        self,
        *,
        persisted_position,
        broker_snapshot,
    ):
        if self.fail_position:
            raise RuntimeError(
                "position restore failed"
            )

        self.positions.append(
            (
                persisted_position,
                broker_snapshot,
            )
        )


def make_recovery_orchestrator():
    orchestrator = (
        TradingRuntimeOrchestrator(
            runtime_id=RuntimeId(
                "NEW-RUNTIME"
            ),
            trading_date=TODAY,
            mode=RuntimeMode.LIVE,
            event_bus=(
                RuntimeEventBus()
            ),
            created_at=NOW,
            recovery_required=True,
        )
    )

    orchestrator.start(
        started_at=NOW
    )

    assert (
        orchestrator.state
        is RuntimeState.RECOVERING
    )

    return orchestrator


def make_recovery_service(
    runtime,
    broker,
    restorer,
):
    return StartupRecoveryService(
        runtime_repository=(
            runtime["runtime_repo"]
        ),
        order_repository=(
            runtime["order_repo"]
        ),
        position_repository=(
            runtime["position_repo"]
        ),
        broker_provider=broker,
        state_restorer=restorer,
    )


def broker_order_snapshot(
    *,
    state=(
        BrokerRecoveryOrderState
        .OPEN
    ),
    filled_quantity=0,
):
    return BrokerRecoveryOrderSnapshot(
        broker_order_id=(
            "BROKER-001"
        ),
        state=state,
        quantity=65,
        filled_quantity=(
            filled_quantity
        ),
        average_fill_price=(
            100
            if filled_quantity
            else None
        ),
        checked_at=NOW,
    )


def broker_position_snapshot(
    *,
    quantity=65,
):
    return BrokerRecoveryPositionSnapshot(
        security_id="41009",
        net_quantity=quantity,
        average_price=100,
        checked_at=NOW,
    )


# ============================================================
# Crash window: persisted runtime / signal
# ============================================================


def test_crash_after_runtime_checkpoint_is_detected_as_interrupted():
    runtime = make_database_runtime()

    runtime[
        "runtime_repo"
    ].add(
        runtime_record(
            state="RUNNING"
        )
    )

    broker = FakeBrokerRecoveryProvider()
    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    plan = service.build_plan(
        trading_date=TODAY
    )

    assert (
        plan.recovery_required
        is True
    )

    assert (
        plan.persisted_runtime_state
        == "RUNNING"
    )

    close_database_runtime(
        runtime
    )


def test_crash_after_signal_persistence_does_not_create_unresolved_order():
    runtime = make_database_runtime()

    runtime[
        "runtime_repo"
    ].add(
        runtime_record()
    )

    runtime[
        "signal_repo"
    ].add(
        signal_record()
    )

    orders = runtime[
        "order_repo"
    ].list_open_orders(
        "OLD-RUNTIME"
    )

    assert orders == ()

    signals = runtime[
        "signal_repo"
    ].list_by_runtime(
        "OLD-RUNTIME"
    )

    assert len(signals) == 1

    close_database_runtime(
        runtime
    )


# ============================================================
# Restart with unresolved BUY
# ============================================================


def test_restart_with_unresolved_buy_requires_broker_query():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = broker_order_snapshot(
        state=(
            BrokerRecoveryOrderState
            .OPEN
        )
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is True

    assert len(
        broker.order_calls
    ) == 1

    assert len(
        restorer.orders
    ) == 1

    close_database_runtime(
        runtime
    )


def test_restart_with_filled_buy_restores_broker_truth():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = broker_order_snapshot(
        state=(
            BrokerRecoveryOrderState
            .FILLED
        ),
        filled_quantity=65,
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        result.recovered_orders
        == 1
    )

    assert (
        orchestrator.state
        is RuntimeState.READY
    )

    close_database_runtime(
        runtime
    )


def test_restart_with_partially_filled_buy_restores_order():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime,
        order=(
            unresolved_order_record(
                status="PARTIALLY_FILLED",
                filled_quantity=30,
            )
        ),
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = broker_order_snapshot(
        state=(
            BrokerRecoveryOrderState
            .PARTIALLY_FILLED
        ),
        filled_quantity=30,
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is True

    assert len(
        restorer.orders
    ) == 1

    close_database_runtime(
        runtime
    )


# ============================================================
# Restart with unresolved SELL
# ============================================================


def test_restart_with_unresolved_sell_is_reconciled_not_duplicated():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime,
        order=(
            unresolved_order_record(
                side="SELL",
                status="SUBMITTED",
            )
        ),
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = broker_order_snapshot(
        state=(
            BrokerRecoveryOrderState
            .OPEN
        )
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        result.recovered_orders
        == 1
    )

    # Recovery only queried/restored.
    # No broker submit API exists on this provider.
    assert len(
        broker.order_calls
    ) == 1

    close_database_runtime(
        runtime
    )


# ============================================================
# Missing broker identity
# ============================================================


def test_unresolved_order_without_broker_id_fails_closed():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime,
        order=(
            unresolved_order_record(
                broker_order_id=None
            )
        ),
    )

    broker = FakeBrokerRecoveryProvider()
    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        result.issues[0].code
        is RecoveryIssueCode
        .ORDER_MISSING_BROKER_ID
    )

    assert (
        orchestrator.state
        is RuntimeState.FAILED
    )

    assert (
        broker.order_calls
        == []
    )

    close_database_runtime(
        runtime
    )


# ============================================================
# Broker NOT_FOUND / UNKNOWN
# ============================================================


def test_broker_not_found_never_assumes_order_cancelled():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = broker_order_snapshot(
        state=(
            BrokerRecoveryOrderState
            .NOT_FOUND
        )
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        result.issues[0].code
        is RecoveryIssueCode
        .ORDER_NOT_FOUND
    )

    assert restorer.orders == []

    close_database_runtime(
        runtime
    )


def test_unknown_order_state_blocks_runtime():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = broker_order_snapshot(
        state=(
            BrokerRecoveryOrderState
            .UNKNOWN
        )
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        orchestrator
        .can_accept_new_entries()
        is False
    )

    assert (
        orchestrator
        .live_execution_allowed()
        is False
    )

    close_database_runtime(
        runtime
    )


# ============================================================
# Broker unavailable
# ============================================================


def test_broker_exception_during_order_recovery_fails_closed():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = RuntimeError(
        "Dhan unavailable"
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        result.issues[0].code
        is RecoveryIssueCode
        .BROKER_QUERY_FAILED
    )

    assert (
        orchestrator.state
        is RuntimeState.FAILED
    )

    close_database_runtime(
        runtime
    )


# ============================================================
# Open position recovery
# ============================================================


def test_restart_with_open_position_queries_broker_position():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime,
        order=(
            unresolved_order_record(
                status="FILLED",
                filled_quantity=65,
            )
        ),
    )

    runtime[
        "position_repo"
    ].add(
        position_record()
    )

    broker = FakeBrokerRecoveryProvider()

    broker.positions[
        "41009"
    ] = broker_position_snapshot(
        quantity=65
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        result.recovered_positions
        == 1
    )

    assert len(
        broker.position_calls
    ) == 1

    close_database_runtime(
        runtime
    )


def test_persisted_position_broker_quantity_mismatch_blocks_recovery():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime,
        order=(
            unresolved_order_record(
                status="FILLED",
                filled_quantity=65,
            )
        ),
    )

    runtime[
        "position_repo"
    ].add(
        position_record(
            open_quantity=65
        )
    )

    broker = FakeBrokerRecoveryProvider()

    broker.positions[
        "41009"
    ] = broker_position_snapshot(
        quantity=35
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        result.issues[0].code
        is RecoveryIssueCode
        .POSITION_QUANTITY_MISMATCH
    )

    assert (
        restorer.positions
        == []
    )

    close_database_runtime(
        runtime
    )


# ============================================================
# Partial position recovery
# ============================================================


def test_restart_with_partial_position_uses_remaining_quantity():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime,
        order=(
            unresolved_order_record(
                status="FILLED",
                filled_quantity=65,
            )
        ),
    )

    runtime[
        "position_repo"
    ].add(
        position_record(
            state="PARTIALLY_EXITED",
            open_quantity=35,
            closed_quantity=30,
        )
    )

    broker = FakeBrokerRecoveryProvider()

    broker.positions[
        "41009"
    ] = broker_position_snapshot(
        quantity=35
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        result.recovered_positions
        == 1
    )

    close_database_runtime(
        runtime
    )


# ============================================================
# Aggregate exposure
# ============================================================


def test_same_contract_multiple_positions_reconcile_against_net_quantity():
    runtime = make_database_runtime()

    runtime[
        "runtime_repo"
    ].add(
        runtime_record()
    )

    runtime[
        "signal_repo"
    ].add(
        signal_record()
    )

    runtime[
        "order_repo"
    ].add(
        unresolved_order_record(
            status="FILLED",
            filled_quantity=65,
        )
    )

    runtime[
        "position_repo"
    ].add(
        position_record(
            position_id="POS-001"
        )
    )

    # Second logical position requires a distinct signal/order.
    runtime[
        "signal_repo"
    ].add(
        SignalRecord(
            signal_id="SIG-002",
            runtime_id="OLD-RUNTIME",
            trading_date=TODAY,
            level="K7",
            signal_type="BUY_CALL",
            option_type="CALL",
            underlying_price=24600,
            quantity=65,
            status="CREATED",
            reason="K7 trigger",
            created_at=NOW,
            updated_at=NOW,
        )
    )

    runtime[
        "order_repo"
    ].add(
        OrderRecord(
            order_intent_id="ORD-002",
            runtime_id="OLD-RUNTIME",
            signal_id="SIG-002",
            position_id=None,
            security_id="41009",
            symbol="NIFTY-CE",
            side="BUY",
            order_type="LIMIT",
            reason="ENTRY",
            quantity=65,
            limit_price=101,
            execution_mode="LIVE",
            status="FILLED",
            broker_name="DHAN",
            broker_order_id="BROKER-002",
            filled_quantity=65,
            average_fill_price=100,
            created_at=NOW,
            submitted_at=NOW,
            updated_at=NOW,
        )
    )

    second = position_record(
        position_id="POS-002"
    )

    second.signal_id = "SIG-002"

    second.entry_order_intent_id = (
        "ORD-002"
    )

    second.risk_id = "RISK:POS-002"
    second.level = "K7"

    runtime[
        "position_repo"
    ].add(
        second
    )

    broker = FakeBrokerRecoveryProvider()

    broker.positions[
        "41009"
    ] = broker_position_snapshot(
        quantity=130
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        result.recovered_positions
        == 2
    )

    assert len(
        broker.position_calls
    ) == 1

    close_database_runtime(
        runtime
    )


# ============================================================
# Restoration failures
# ============================================================


def test_order_restorer_exception_blocks_recovery():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = broker_order_snapshot()

    restorer = FakeRecoveryRestorer(
        fail_order=True
    )

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        result.issues[0].code
        is RecoveryIssueCode
        .RESTORE_FAILED
    )

    close_database_runtime(
        runtime
    )


def test_position_restorer_exception_blocks_recovery():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime,
        order=(
            unresolved_order_record(
                status="FILLED",
                filled_quantity=65,
            )
        ),
    )

    runtime[
        "position_repo"
    ].add(
        position_record()
    )

    broker = FakeBrokerRecoveryProvider()

    broker.positions[
        "41009"
    ] = broker_position_snapshot()

    restorer = FakeRecoveryRestorer(
        fail_position=True
    )

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        result.issues[0].code
        is RecoveryIssueCode
        .RESTORE_FAILED
    )

    close_database_runtime(
        runtime
    )


# ============================================================
# Runtime transition safety
# ============================================================


def test_recover_cannot_run_from_ready_runtime():
    runtime = make_database_runtime()

    broker = FakeBrokerRecoveryProvider()
    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        TradingRuntimeOrchestrator(
            runtime_id=RuntimeId(
                "NEW-RUNTIME"
            ),
            trading_date=TODAY,
            mode=RuntimeMode.LIVE,
            event_bus=(
                RuntimeEventBus()
            ),
            created_at=NOW,
            recovery_required=False,
        )
    )

    orchestrator.start(
        started_at=NOW
    )

    assert (
        orchestrator.state
        is RuntimeState.READY
    )

    with pytest.raises(
        RuntimeTransitionError
    ):
        service.recover(
            orchestrator=orchestrator,
            source_runtime_id=(
                "OLD-RUNTIME"
            ),
            checked_at=NOW,
        )

    close_database_runtime(
        runtime
    )


def test_recovering_runtime_cannot_run_before_recovery_complete():
    orchestrator = (
        make_recovery_orchestrator()
    )

    with pytest.raises(
        RuntimeTransitionError,
        match=(
            "runtime can only run from READY"
        ),
    ):
        orchestrator.run(
            running_at=NOW
        )


def test_successful_recovery_must_reach_ready_before_running():
    runtime = make_database_runtime()

    broker = FakeBrokerRecoveryProvider()
    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    result = service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        orchestrator.state
        is RuntimeState.READY
    )

    orchestrator.run(
        running_at=LATER
    )

    assert (
        orchestrator.state
        is RuntimeState.RUNNING
    )

    close_database_runtime(
        runtime
    )


def test_failed_recovery_never_allows_running():
    runtime = make_database_runtime()

    seed_runtime_signal_order(
        runtime
    )

    broker = FakeBrokerRecoveryProvider()

    broker.orders[
        "BROKER-001"
    ] = broker_order_snapshot(
        state=(
            BrokerRecoveryOrderState
            .UNKNOWN
        )
    )

    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    orchestrator = (
        make_recovery_orchestrator()
    )

    service.recover(
        orchestrator=orchestrator,
        source_runtime_id="OLD-RUNTIME",
        checked_at=NOW,
    )

    assert (
        orchestrator.state
        is RuntimeState.FAILED
    )

    with pytest.raises(
        RuntimeTransitionError
    ):
        orchestrator.run(
            running_at=LATER
        )

    close_database_runtime(
        runtime
    )


# ============================================================
# Clean STOPPED runtime
# ============================================================


def test_clean_stopped_runtime_without_exposure_needs_no_recovery():
    runtime = make_database_runtime()

    runtime[
        "runtime_repo"
    ].add(
        runtime_record(
            state="STOPPED"
        )
    )

    broker = FakeBrokerRecoveryProvider()
    restorer = FakeRecoveryRestorer()

    service = make_recovery_service(
        runtime,
        broker,
        restorer,
    )

    plan = service.build_plan(
        trading_date=TODAY
    )

    assert (
        plan.recovery_required
        is False
    )

    assert (
        plan.unresolved_order_count
        == 0
    )

    assert (
        plan.open_position_count
        == 0
    )

    close_database_runtime(
        runtime
    )


# ============================================================
# Audit idempotency
# ============================================================


def test_duplicate_event_checkpoint_is_not_silently_accepted():
    runtime = make_database_runtime()

    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "AUDIT-RUNTIME"
        ),
        trading_date=TODAY,
        mode=RuntimeMode.DRY_RUN,
        state=RuntimeState.RUNNING,
        started_at=NOW,
        updated_at=NOW,
    )

    runtime[
        "checkpoint"
    ].checkpoint_runtime(
        snapshot
    )

    event = RuntimeEvent(
        event_id="EVENT-001",
        runtime_id=RuntimeId(
            "AUDIT-RUNTIME"
        ),
        event_type=(
            RuntimeEventType
            .SIGNAL_CREATED
        ),
        occurred_at=NOW,
    )

    runtime[
        "checkpoint"
    ].checkpoint_event(
        event
    )

    with pytest.raises(
        PersistenceCheckpointError
    ):
        runtime[
            "checkpoint"
        ].checkpoint_event(
            event
        )

    close_database_runtime(
        runtime
    )


# ============================================================
# Database failure boundary
# ============================================================


def test_checkpoint_fails_when_session_manager_stopped():
    runtime = make_database_runtime()

    runtime[
        "sessions"
    ].stop()

    snapshot = RuntimeSnapshot(
        runtime_id=RuntimeId(
            "DB-FAIL"
        ),
        trading_date=TODAY,
        mode=RuntimeMode.LIVE,
        state=RuntimeState.RUNNING,
        started_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(
        PersistenceCheckpointError
    ):
        runtime[
            "checkpoint"
        ].checkpoint_runtime(
            snapshot
        )

    runtime[
        "database"
    ].dispose()


# ============================================================
# Pipeline crash windows
# ============================================================


@dataclass(frozen=True)
class FakeSignal:
    signal_id: str = "SIG-PIPELINE"


@dataclass(frozen=True)
class FakeOption:
    selection_id: str = "SEL-PIPELINE"


@dataclass(frozen=True)
class FakeExecution:
    order_intent_id: str = (
        "ORD-PIPELINE"
    )

    filled: bool = True


class StrategyAlwaysSignals:
    def process_market_data(
        self,
        market_data,
        *,
        processed_at,
    ):
        del market_data
        del processed_at
        return "STRATEGY-RESULT"


class SignalAlwaysBuilds:
    def build_signal(
        self,
        strategy_result,
        *,
        created_at,
    ):
        del strategy_result
        del created_at
        return FakeSignal()


class OptionAlwaysSelects:
    def select_option(
        self,
        signal,
        *,
        selected_at,
    ):
        del signal
        del selected_at
        return FakeOption()


class EntryCounter:
    def __init__(self):
        self.count = 0

    def execute_entry(
        self,
        *,
        signal,
        selected_option,
        dry_run,
        requested_at,
    ):
        del signal
        del selected_option
        del dry_run
        del requested_at

        self.count += 1

        return FakeExecution()


class NoRiskDecisions:
    def process_market_data(
        self,
        market_data,
        *,
        processed_at,
    ):
        del market_data
        del processed_at
        return ()

    def register_entry_fill(
        self,
        entry_execution,
        *,
        registered_at,
    ):
        del entry_execution
        del registered_at
        return None

    def apply_exit_fill(
        self,
        exit_execution,
        *,
        applied_at,
    ):
        del exit_execution
        del applied_at
        return None


class NeverExit:
    def execute_exit(
        self,
        decision,
        *,
        dry_run,
        requested_at,
    ):
        raise AssertionError(
            "exit should not execute"
        )


class FailingPipelinePersistence:
    def __init__(
        self,
        fail_on,
    ):
        self.fail_on = fail_on

    def _check(
        self,
        name,
    ):
        if self.fail_on == name:
            raise RuntimeError(
                f"{name} persistence failed"
            )

    def persist_signal(
        self,
        signal,
    ):
        del signal
        self._check("SIGNAL")

    def persist_option_selection(
        self,
        *,
        signal,
        selected_option,
    ):
        del signal
        del selected_option
        self._check("OPTION")

    def persist_entry_execution(
        self,
        entry_execution,
    ):
        del entry_execution
        self._check("ENTRY")

    def persist_position(
        self,
        position,
    ):
        del position
        self._check("POSITION")

    def persist_exit_execution(
        self,
        exit_execution,
    ):
        del exit_execution
        self._check("EXIT")


def make_pipeline(
    *,
    fail_on,
):
    bus = RuntimeEventBus()

    orchestrator = (
        TradingRuntimeOrchestrator(
            runtime_id=RuntimeId(
                "PIPELINE-RUNTIME"
            ),
            trading_date=TODAY,
            mode=RuntimeMode.LIVE,
            event_bus=bus,
            created_at=NOW,
        )
    )

    orchestrator.start(
        started_at=NOW
    )

    orchestrator.run(
        running_at=NOW
    )

    entry = EntryCounter()

    pipeline = TradingRuntimePipeline(
        orchestrator=orchestrator,
        event_bus=bus,
        strategy=(
            StrategyAlwaysSignals()
        ),
        signal_engine=(
            SignalAlwaysBuilds()
        ),
        option_selection=(
            OptionAlwaysSelects()
        ),
        entry_execution=entry,
        position_risk=(
            NoRiskDecisions()
        ),
        exit_execution=NeverExit(),
        persistence=(
            FailingPipelinePersistence(
                fail_on
            )
        ),
    )

    return (
        orchestrator,
        entry,
        pipeline,
    )


def test_signal_persistence_failure_prevents_broker_entry_call():
    (
        orchestrator,
        entry,
        pipeline,
    ) = make_pipeline(
        fail_on="SIGNAL"
    )

    with pytest.raises(
        TradingPipelineError
    ):
        pipeline.process_market_data(
            24600,
            processed_at=NOW,
        )

    assert entry.count == 0

    assert (
        orchestrator.state
        is RuntimeState.FAILED
    )


def test_option_persistence_failure_prevents_broker_entry_call():
    (
        orchestrator,
        entry,
        pipeline,
    ) = make_pipeline(
        fail_on="OPTION"
    )

    with pytest.raises(
        TradingPipelineError
    ):
        pipeline.process_market_data(
            24600,
            processed_at=NOW,
        )

    assert entry.count == 0

    assert (
        orchestrator.state
        is RuntimeState.FAILED
    )


def test_entry_result_persistence_failure_fails_runtime():
    (
        orchestrator,
        entry,
        pipeline,
    ) = make_pipeline(
        fail_on="ENTRY"
    )

    with pytest.raises(
        TradingPipelineError
    ):
        pipeline.process_market_data(
            24600,
            processed_at=NOW,
        )

    # Broker-facing entry boundary was already called.
    assert entry.count == 1

    # Because result persistence failed, runtime MUST fail.
    assert (
        orchestrator.state
        is RuntimeState.FAILED
    )

    assert (
        orchestrator
        .can_accept_new_entries()
        is False
    )


# ============================================================
# 15:15 recovery semantics
# ============================================================


def test_recovery_at_1515_still_blocks_new_entries():
    orchestrator = (
        TradingRuntimeOrchestrator(
            runtime_id=RuntimeId(
                "FORCE-EXIT-RECOVERY"
            ),
            trading_date=TODAY,
            mode=RuntimeMode.LIVE,
            event_bus=(
                RuntimeEventBus()
            ),
            created_at=NOW,
            recovery_required=True,
        )
    )

    orchestrator.start(
        started_at=(
            FORCE_EXIT_TIME
        )
    )

    assert (
        orchestrator.state
        is RuntimeState.RECOVERING
    )

    assert (
        orchestrator
        .can_accept_new_entries()
        is False
    )

    assert (
        orchestrator
        .live_execution_allowed()
        is False
    )


# ============================================================
# Failure remains terminal for current runtime
# ============================================================


def test_failed_runtime_cannot_be_restarted_in_place():
    orchestrator = (
        TradingRuntimeOrchestrator(
            runtime_id=RuntimeId(
                "FAILED-RUNTIME"
            ),
            trading_date=TODAY,
            mode=RuntimeMode.LIVE,
            event_bus=(
                RuntimeEventBus()
            ),
            created_at=NOW,
        )
    )

    orchestrator.start(
        started_at=NOW
    )

    orchestrator.fail(
        code=(
            RuntimeFailureCode
            .DATABASE_FAILED
        ),
        message="database failed",
        failed_at=LATER,
        component="database",
        recoverable=True,
    )

    assert (
        orchestrator.state
        is RuntimeState.FAILED
    )

    with pytest.raises(
        RuntimeTransitionError
    ):
        orchestrator.start(
            started_at=(
                LATER
                + timedelta(seconds=1)
            )
        )


def test_failed_runtime_blocks_entry_and_live_execution():
    orchestrator = (
        TradingRuntimeOrchestrator(
            runtime_id=RuntimeId(
                "FAILED-RUNTIME"
            ),
            trading_date=TODAY,
            mode=RuntimeMode.LIVE,
            event_bus=(
                RuntimeEventBus()
            ),
            created_at=NOW,
        )
    )

    orchestrator.start(
        started_at=NOW
    )

    orchestrator.run(
        running_at=NOW
    )

    orchestrator.fail(
        code=(
            RuntimeFailureCode
            .RECOVERY_FAILED
        ),
        message="uncertain broker state",
        failed_at=LATER,
        component=(
            "startup-recovery"
        ),
        recoverable=True,
    )

    assert (
        orchestrator
        .can_accept_new_entries()
        is False
    )

    assert (
        orchestrator
        .live_execution_allowed()
        is False
    )