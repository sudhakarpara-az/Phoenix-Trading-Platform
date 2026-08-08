"""
Phoenix M08-T08 Startup Recovery tests.
"""

from datetime import (
    date,
    datetime,
)
from types import SimpleNamespace

import pytest

from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.recovery_types import (
    BrokerRecoveryOrderSnapshot,
    BrokerRecoveryOrderState,
    BrokerRecoveryPositionSnapshot,
)
from src.runtime.runtime_orchestrator import (
    RuntimeTransitionError,
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
    RuntimeState,
)
from src.runtime.startup_recovery_service import (
    StartupRecoveryService,
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


class FakeRuntimeRepository:
    def __init__(
        self,
        runtime=None,
    ):
        self.runtime = runtime

    def latest_for_trading_date(
        self,
        trading_date,
    ):
        del trading_date
        return self.runtime


class FakeOrderRepository:
    def __init__(
        self,
        orders=(),
    ):
        self.orders = tuple(
            orders
        )

    def list_open_orders(
        self,
        runtime_id,
    ):
        del runtime_id
        return self.orders


class FakePositionRepository:
    def __init__(
        self,
        positions=(),
    ):
        self.positions = tuple(
            positions
        )

    def list_open_positions(
        self,
        runtime_id,
    ):
        del runtime_id
        return self.positions


class FakeBroker:
    def __init__(
        self,
    ):
        self.orders = {}
        self.positions = {}

    def get_order_snapshot(
        self,
        *,
        broker_order_id,
        checked_at,
    ):
        del checked_at

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
        del checked_at

        value = self.positions[
            security_id
        ]

        if isinstance(
            value,
            Exception,
        ):
            raise value

        return value


class FakeRestorer:
    def __init__(
        self,
    ):
        self.orders = []
        self.positions = []

    def restore_order(
        self,
        *,
        persisted_order,
        broker_snapshot,
    ):
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
        self.positions.append(
            (
                persisted_position,
                broker_snapshot,
            )
        )


def make_orchestrator(
    *,
    recovery_required=True,
):
    runtime = TradingRuntimeOrchestrator(
        runtime_id=RuntimeId(
            "CURRENT-RUNTIME"
        ),
        trading_date=TODAY,
        mode=RuntimeMode.DRY_RUN,
        event_bus=RuntimeEventBus(),
        created_at=NOW,
        recovery_required=(
            recovery_required
        ),
    )

    runtime.start(
        started_at=NOW
    )

    return runtime


def make_service(
    *,
    persisted_runtime=None,
    orders=(),
    positions=(),
):
    runtime_repo = FakeRuntimeRepository(
        persisted_runtime
    )

    order_repo = FakeOrderRepository(
        orders
    )

    position_repo = (
        FakePositionRepository(
            positions
        )
    )

    broker = FakeBroker()
    restorer = FakeRestorer()

    service = StartupRecoveryService(
        runtime_repository=runtime_repo,
        order_repository=order_repo,
        position_repository=(
            position_repo
        ),
        broker_provider=broker,
        state_restorer=restorer,
    )

    return (
        service,
        broker,
        restorer,
    )


def order(
    *,
    order_id="ORD-001",
    broker_id="BROKER-001",
):
    return SimpleNamespace(
        order_intent_id=order_id,
        broker_order_id=broker_id,
    )


def position(
    *,
    position_id="POS-001",
    security_id="41009",
    quantity=65,
):
    return SimpleNamespace(
        position_id=position_id,
        security_id=security_id,
        open_quantity=quantity,
    )


def broker_order(
    *,
    broker_id="BROKER-001",
    state=(
        BrokerRecoveryOrderState.OPEN
    ),
    quantity=65,
    filled_quantity=0,
):
    return BrokerRecoveryOrderSnapshot(
        broker_order_id=broker_id,
        state=state,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_fill_price=None,
        checked_at=NOW,
    )


def broker_position(
    *,
    security_id="41009",
    quantity=65,
):
    return BrokerRecoveryPositionSnapshot(
        security_id=security_id,
        net_quantity=quantity,
        average_price=100,
        checked_at=NOW,
    )


# ============================================================
# Discovery
# ============================================================


def test_no_previous_runtime_requires_no_recovery():
    service, _, _ = make_service()

    plan = service.build_plan(
        trading_date=TODAY
    )

    assert (
        plan.recovery_required
        is False
    )

    assert (
        plan.source_runtime_id
        is None
    )


def test_clean_stopped_runtime_requires_no_recovery():
    persisted = SimpleNamespace(
        runtime_id="OLD",
        state="STOPPED",
    )

    service, _, _ = make_service(
        persisted_runtime=persisted
    )

    plan = service.build_plan(
        trading_date=TODAY
    )

    assert (
        plan.recovery_required
        is False
    )


def test_interrupted_runtime_requires_recovery():
    persisted = SimpleNamespace(
        runtime_id="OLD",
        state="RUNNING",
    )

    service, _, _ = make_service(
        persisted_runtime=persisted
    )

    plan = service.build_plan(
        trading_date=TODAY
    )

    assert (
        plan.recovery_required
        is True
    )


def test_open_order_requires_recovery_even_if_stopped():
    persisted = SimpleNamespace(
        runtime_id="OLD",
        state="STOPPED",
    )

    service, _, _ = make_service(
        persisted_runtime=persisted,
        orders=[
            order()
        ],
    )

    plan = service.build_plan(
        trading_date=TODAY
    )

    assert (
        plan.recovery_required
        is True
    )

    assert (
        plan.unresolved_order_count
        == 1
    )


def test_open_position_requires_recovery():
    persisted = SimpleNamespace(
        runtime_id="OLD",
        state="STOPPED",
    )

    service, _, _ = make_service(
        persisted_runtime=persisted,
        positions=[
            position()
        ],
    )

    plan = service.build_plan(
        trading_date=TODAY
    )

    assert (
        plan.recovery_required
        is True
    )


# ============================================================
# Order recovery
# ============================================================


def test_confirmed_order_is_restored():
    persisted_order = order()

    service, broker, restorer = (
        make_service(
            orders=[
                persisted_order
            ]
        )
    )

    broker.orders[
        "BROKER-001"
    ] = broker_order()

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        result.recovered_orders
        == 1
    )

    assert len(
        restorer.orders
    ) == 1

    assert (
        runtime.state
        is RuntimeState.READY
    )


def test_missing_broker_order_id_fails_recovery():
    service, _, restorer = (
        make_service(
            orders=[
                order(
                    broker_id=None
                )
            ]
        )
    )

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is False
    assert result.issue_count == 1

    assert (
        runtime.state
        is RuntimeState.FAILED
    )

    assert restorer.orders == []


def test_unknown_broker_order_fails_recovery():
    service, broker, _ = (
        make_service(
            orders=[
                order()
            ]
        )
    )

    broker.orders[
        "BROKER-001"
    ] = broker_order(
        state=(
            BrokerRecoveryOrderState
            .UNKNOWN
        )
    )

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        runtime.state
        is RuntimeState.FAILED
    )


def test_not_found_broker_order_fails_recovery():
    service, broker, _ = (
        make_service(
            orders=[
                order()
            ]
        )
    )

    broker.orders[
        "BROKER-001"
    ] = broker_order(
        state=(
            BrokerRecoveryOrderState
            .NOT_FOUND
        )
    )

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is False


def test_broker_query_exception_fails_closed():
    service, broker, _ = (
        make_service(
            orders=[
                order()
            ]
        )
    )

    broker.orders[
        "BROKER-001"
    ] = RuntimeError(
        "broker unavailable"
    )

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is False

    assert (
        runtime.state
        is RuntimeState.FAILED
    )


# ============================================================
# Position recovery
# ============================================================


def test_matching_position_is_restored():
    persisted_position = (
        position()
    )

    service, broker, restorer = (
        make_service(
            positions=[
                persisted_position
            ]
        )
    )

    broker.positions[
        "41009"
    ] = broker_position()

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        result.recovered_positions
        == 1
    )

    assert len(
        restorer.positions
    ) == 1


def test_position_quantity_mismatch_fails():
    service, broker, restorer = (
        make_service(
            positions=[
                position(
                    quantity=65
                )
            ]
        )
    )

    broker.positions[
        "41009"
    ] = broker_position(
        quantity=35
    )

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is False

    assert restorer.positions == []

    assert (
        runtime.state
        is RuntimeState.FAILED
    )


def test_same_security_positions_compare_aggregate():
    first = position(
        position_id="POS-1",
        security_id="41009",
        quantity=65,
    )

    second = position(
        position_id="POS-2",
        security_id="41009",
        quantity=65,
    )

    service, broker, restorer = (
        make_service(
            positions=[
                first,
                second,
            ]
        )
    )

    broker.positions[
        "41009"
    ] = broker_position(
        quantity=130
    )

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is True

    assert (
        result.recovered_positions
        == 2
    )

    assert len(
        restorer.positions
    ) == 2


def test_same_security_positions_do_not_compare_each_to_net():
    first = position(
        position_id="POS-1",
        quantity=65,
    )

    second = position(
        position_id="POS-2",
        quantity=65,
    )

    service, broker, _ = (
        make_service(
            positions=[
                first,
                second,
            ]
        )
    )

    broker.positions[
        "41009"
    ] = broker_position(
        quantity=65
    )

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is False

    assert result.issue_count == 2


# ============================================================
# Recovery gate
# ============================================================


def test_recovery_requires_recovering_runtime():
    service, _, _ = make_service()

    runtime = make_orchestrator(
        recovery_required=False
    )

    # Clean startup reaches READY.
    assert (
        runtime.state
        is RuntimeState.READY
    )

    with pytest.raises(
        RuntimeTransitionError,
        match=(
            "startup recovery requires "
            "RECOVERING runtime state"
        ),
    ):
        service.recover(
            orchestrator=runtime,
            source_runtime_id="OLD",
            checked_at=NOW,
        )


def test_empty_recovery_completes_successfully():
    service, _, _ = make_service()

    runtime = make_orchestrator()

    result = service.recover(
        orchestrator=runtime,
        source_runtime_id="OLD",
        checked_at=NOW,
    )

    assert result.completed is True
    assert result.issue_count == 0

    assert (
        runtime.state
        is RuntimeState.READY
    )

    assert (
        runtime.snapshot.recovered
        is True
    )