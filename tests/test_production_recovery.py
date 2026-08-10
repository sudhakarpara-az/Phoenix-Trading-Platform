"""
M10 concrete production crash-restart recovery tests.

No live Dhan request is made.
"""

from __future__ import annotations

from datetime import (
    date,
    datetime,
    timedelta,
)
from threading import RLock
from typing import (
    Any,
    cast,
)

import pytest

from src.account.account_types import (
    BrokerAccountId,
)
from src.app.recovery import (
    PhoenixDhanRecoveryProvider,
    PhoenixRecoveryError,
    PhoenixRecoveryStateRestorer,
    RecoveryStateRestorerBinding,
)
from src.database.engine import (
    DatabaseConfig,
)
from src.database.exit_durability import (
    SQLAlchemyExitPersistenceService,
)
from src.database.schema import (
    OptionSelectionRecord,
    OrderRecord,
    PositionRecord,
    RuntimeSessionRecord,
    SignalRecord,
)
from src.execution.dhan_order_adapter import (
    DhanOrderAdapter,
)
from src.execution.execution_service import (
    ExecutionService,
)
from src.execution.execution_types import (
    BrokerOrderStatus,
)
from src.execution.exit_execution_service import (
    ExitExecutionService,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
    IdempotencyKey,
    IdempotencyRecord,
    IdempotencyState,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.runtime.recovery_types import (
    BrokerRecoveryOrderSnapshot,
    BrokerRecoveryOrderState,
    BrokerRecoveryPositionSnapshot,
)
from src.strategy.strategy_types import (
    EntryLevel,
)
from src.app.container import (
    build_persistence_foundation,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

OPENED_AT = datetime(
    2026,
    8,
    10,
    9,
    30,
)

RECOVERY_AT = datetime(
    2026,
    8,
    10,
    15,
    20,
)

SOURCE_RUNTIME = (
    "RECOVERY-SOURCE-001"
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-RECOVERY-001"
)

SIGNAL_ID = (
    "SIG-RECOVERY-001"
)

ENTRY_ORDER_ID = (
    "ORD-20260810-000007"
)

POSITION_ID = (
    "POS-RECOVERY-001"
)

SELL_ORDER_ID = (
    "EXIT-20260810-000011"
)

SYMBOL = (
    "NIFTY50-20260811-24450-CE"
)


class FakeDhanClient:
    def __init__(
        self,
    ) -> None:
        self.order_response: Any = {
            "orderId": "DHAN-ORDER-001",
            "orderStatus": "OPEN",
            "quantity": 65,
            "filledQty": 0,
            "averageTradedPrice": 0,
        }

        self.position_response: Any = []

        self.order_calls = 0
        self.position_calls = 0

    def get_order_by_id(
        self,
        *,
        order_id: str,
    ) -> Any:
        self.order_calls += 1

        response = dict(
            self.order_response
        )

        response[
            "orderId"
        ] = order_id

        return response

    def get_positions(
        self,
    ) -> Any:
        self.position_calls += 1

        return self.position_response


def require_guard_record(
    guard: DuplicateOrderGuard,
    key: IdempotencyKey,
) -> IdempotencyRecord:
    record = guard.get(
        key
    )

    assert record is not None

    return record


class StubRestorer:
    def restore_order(
        self,
        *,
        persisted_order: object,
        broker_snapshot:
            BrokerRecoveryOrderSnapshot,
    ) -> None:
        del persisted_order
        del broker_snapshot

    def restore_position(
        self,
        *,
        persisted_position: object,
        broker_snapshot:
            BrokerRecoveryPositionSnapshot,
    ) -> None:
        del persisted_position
        del broker_snapshot


def make_entry_execution_shell(
) -> ExecutionService:
    service = cast(
        Any,
        object.__new__(
            ExecutionService
        ),
    )

    service._state_machine = (
        OrderStateMachine()
    )

    service._idempotency_guard = (
        DuplicateOrderGuard()
    )

    service._sequence = 0

    service._sequence_lock = (
        RLock()
    )

    return cast(
        ExecutionService,
        service,
    )


def make_exit_execution_shell(
    guard: DuplicateOrderGuard,
) -> ExitExecutionService:
    service = cast(
        Any,
        object.__new__(
            ExitExecutionService
        ),
    )

    service._duplicate_guard = (
        guard
    )

    service._sequence = 0

    service._sequence_lock = (
        RLock()
    )

    return cast(
        ExitExecutionService,
        service,
    )


def seed_runtime(
    persistence,
) -> None:
    persistence.runtime_repository.add(
        RuntimeSessionRecord(
            runtime_id=SOURCE_RUNTIME,
            trading_date=TRADING_DATE,
            mode="LIVE",
            state="RUNNING",
            started_at=OPENED_AT,
            updated_at=RECOVERY_AT,
            recovery_required=True,
            recovered=False,
        )
    )


def seed_signal(
    persistence,
) -> None:
    persistence.signal_repository.add(
        SignalRecord(
            signal_id=SIGNAL_ID,
            runtime_id=SOURCE_RUNTIME,
            trading_date=TRADING_DATE,
            level="K5",
            signal_type="BUY_CALL",
            option_type="CALL",
            underlying_price=24600,
            quantity=65,
            status="CREATED",
            reason="K5 trigger",
            created_at=OPENED_AT,
            updated_at=OPENED_AT,
        )
    )


def seed_selection(
    persistence,
) -> None:
    persistence.option_selection_repository.add(
        OptionSelectionRecord(
            selection_id=(
                "SEL-RECOVERY-001"
            ),
            runtime_id=SOURCE_RUNTIME,
            signal_id=SIGNAL_ID,
            underlying_symbol="NIFTY 50",
            symbol=SYMBOL,
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
            target_delta=0.60,
            bid=99.95,
            ask=100.05,
            volume=1000,
            open_interest=50000,
            quote_received_at=(
                OPENED_AT
            ),
            selected_at=OPENED_AT,
        )
    )


def seed_entry_order(
    persistence,
    *,
    status: str = "FILLED",
    position_id: str | None = POSITION_ID,
) -> None:
    persistence.order_repository.add(
        OrderRecord(
            order_intent_id=ENTRY_ORDER_ID,
            runtime_id=SOURCE_RUNTIME,
            signal_id=SIGNAL_ID,
            position_id=position_id,
            security_id="41009",
            symbol=SYMBOL,
            side="BUY",
            order_type="LIMIT",
            reason="K5",
            quantity=65,
            limit_price=101,
            execution_mode="LIVE",
            status=status,
            broker_name="DHAN",
            broker_order_id=(
                "DHAN-ENTRY-001"
            ),
            filled_quantity=(
                65
                if status == "FILLED"
                else 0
            ),
            average_fill_price=(
                100
                if status == "FILLED"
                else None
            ),
            created_at=OPENED_AT,
            submitted_at=OPENED_AT,
            updated_at=OPENED_AT,
        )
    )


def seed_position(
    persistence,
    *,
    state: str = "OPEN",
    open_quantity: int = 65,
    closed_quantity: int = 0,
    realized_pnl: float = 0,
) -> None:
    persistence.position_repository.add(
        PositionRecord(
            position_id=POSITION_ID,
            risk_id=(
                f"RISK:{POSITION_ID}"
            ),
            runtime_id=SOURCE_RUNTIME,
            signal_id=SIGNAL_ID,
            entry_order_intent_id=(
                ENTRY_ORDER_ID
            ),
            security_id="41009",
            symbol=SYMBOL,
            option_type="CALL",
            level="K5",
            original_quantity=65,
            open_quantity=open_quantity,
            closed_quantity=(
                closed_quantity
            ),
            entry_price=100,
            realized_pnl=realized_pnl,
            state=state,
            stop_price=85,
            stop_risk_points=15,
            stop_state="ARMED",
            executable_target_price=127,
            mapped_target_price=130,
            booking_zone_start=127,
            booking_zone_end=130,
            target_state="ARMED",
            opened_at=OPENED_AT,
            updated_at=OPENED_AT,
            closed_at=None,
        )
    )


def seed_sell_order(
    persistence,
) -> None:
    persistence.order_repository.add(
        OrderRecord(
            order_intent_id=(
                SELL_ORDER_ID
            ),
            runtime_id=SOURCE_RUNTIME,
            signal_id=None,
            position_id=POSITION_ID,
            security_id="41009",
            symbol=SYMBOL,
            side="SELL",
            order_type="MARKET",
            reason="FORCE_EXIT",
            quantity=65,
            limit_price=None,
            execution_mode="LIVE",
            status="SUBMITTED",
            broker_name="DHAN",
            broker_order_id=(
                "DHAN-SELL-001"
            ),
            filled_quantity=0,
            average_fill_price=None,
            created_at=(
                OPENED_AT
                + timedelta(
                    hours=5,
                )
            ),
            submitted_at=(
                OPENED_AT
                + timedelta(
                    hours=5,
                )
            ),
            updated_at=(
                OPENED_AT
                + timedelta(
                    hours=5,
                )
            ),
        )
    )


def make_restorer(
    persistence,
    *,
    source_runtime_id: str | None = (
        SOURCE_RUNTIME
    ),
):
    entry_service = (
        make_entry_execution_shell()
    )

    exit_guard = (
        DuplicateOrderGuard()
    )

    exit_service = (
        make_exit_execution_shell(
            exit_guard
        )
    )

    registry = (
        PositionRegistry()
    )

    lifecycle = (
        PositionLifecycleManager(
            registry=registry
        )
    )

    exit_persistence = None

    if source_runtime_id is not None:
        exit_persistence = (
            SQLAlchemyExitPersistenceService(
                runtime_id=(
                    source_runtime_id
                ),
                order_repository=(
                    persistence
                    .order_repository
                ),
                fill_repository=(
                    persistence
                    .order_fill_repository
                ),
                position_repository=(
                    persistence
                    .position_repository
                ),
            )
        )

    restorer = (
        PhoenixRecoveryStateRestorer(
            source_runtime_id=(
                source_runtime_id
            ),
            trading_date=TRADING_DATE,
            option_selection_repository=(
                persistence
                .option_selection_repository
            ),
            order_repository=(
                persistence
                .order_repository
            ),
            position_repository=(
                persistence
                .position_repository
            ),
            execution_service=(
                entry_service
            ),
            exit_execution_service=(
                exit_service
            ),
            exit_persistence=(
                exit_persistence
            ),
            position_registry=registry,
            position_lifecycle_manager=(
                lifecycle
            ),
            exit_duplicate_guard=(
                exit_guard
            ),
        )
    )

    return (
        restorer,
        entry_service,
        exit_service,
        exit_guard,
        registry,
    )


# ============================================================
# Deferred binding
# ============================================================


def test_recovery_binding_fails_closed_until_bound():
    binding = (
        RecoveryStateRestorerBinding()
    )

    assert binding.is_bound is False

    with pytest.raises(
        PhoenixRecoveryError,
        match="has not been bound",
    ):
        binding.restore_order(
            persisted_order=object(),
            broker_snapshot=(
                BrokerRecoveryOrderSnapshot(
                    broker_order_id="B1",
                    state=(
                        BrokerRecoveryOrderState
                        .OPEN
                    ),
                    quantity=65,
                    filled_quantity=0,
                    average_fill_price=None,
                    checked_at=RECOVERY_AT,
                )
            ),
        )

    delegate = StubRestorer()

    binding.bind(
        delegate
    )

    assert binding.is_bound is True
    assert binding.delegate is delegate

    with pytest.raises(
        RuntimeError,
        match="already bound",
    ):
        binding.bind(
            StubRestorer()
        )


# ============================================================
# Dhan provider
# ============================================================


def test_dhan_recovery_provider_maps_order_truth():
    client = FakeDhanClient()

    client.order_response = {
        "orderStatus":
            "PART_TRADED",
        "quantity": 65,
        "filledQty": 20,
        "averageTradedPrice": 126,
    }

    adapter = DhanOrderAdapter(
        client
    )

    provider = (
        PhoenixDhanRecoveryProvider(
            order_adapter=adapter,
            dhan_client=client,
            account_id=ACCOUNT_ID,
        )
    )

    result = (
        provider.get_order_snapshot(
            broker_order_id="B-123",
            checked_at=RECOVERY_AT,
        )
    )

    assert (
        result.state
        is BrokerRecoveryOrderState
        .PARTIALLY_FILLED
    )

    assert result.quantity == 65
    assert result.filled_quantity == 20
    assert result.average_fill_price == 126
    assert client.order_calls == 1


def test_dhan_recovery_provider_aggregates_position_truth():
    client = FakeDhanClient()

    client.position_response = {
        "status": "success",
        "data": [
            {
                "dhanClientId":
                    ACCOUNT_ID.value,
                "securityId":
                    "41009",
                "netQty": 35,
            },
            {
                "dhanClientId":
                    ACCOUNT_ID.value,
                "securityId":
                    "41009",
                "netQty": 30,
            },
            {
                "dhanClientId":
                    ACCOUNT_ID.value,
                "securityId":
                    "99999",
                "netQty": 10,
            },
        ],
    }

    provider = (
        PhoenixDhanRecoveryProvider(
            order_adapter=(
                DhanOrderAdapter(
                    client
                )
            ),
            dhan_client=client,
            account_id=ACCOUNT_ID,
        )
    )

    result = (
        provider.get_position_snapshot(
            security_id="41009",
            checked_at=RECOVERY_AT,
        )
    )

    assert result.net_quantity == 65
    assert result.average_price is None
    assert client.position_calls == 1


def test_dhan_position_account_mismatch_fails_closed():
    client = FakeDhanClient()

    client.position_response = [
        {
            "dhanClientId": "OTHER",
            "securityId": "41009",
            "netQty": 65,
        }
    ]

    provider = (
        PhoenixDhanRecoveryProvider(
            order_adapter=(
                DhanOrderAdapter(
                    client
                )
            ),
            dhan_client=client,
            account_id=ACCOUNT_ID,
        )
    )

    with pytest.raises(
        PhoenixRecoveryError,
        match="configured account",
    ):
        provider.get_position_snapshot(
            security_id="41009",
            checked_at=RECOVERY_AT,
        )


# ============================================================
# Sequence-floor reconstruction
# ============================================================


def test_restorer_recovers_buy_and_sell_sequence_floors():
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        seed_runtime(
            persistence
        )

        seed_signal(
            persistence
        )

        seed_entry_order(
            persistence,
            status="SUBMITTED",
            position_id=None,
        )

        persistence.order_repository.add(
            OrderRecord(
                order_intent_id=(
                    SELL_ORDER_ID
                ),
                runtime_id=SOURCE_RUNTIME,
                signal_id=None,
                position_id="P-X",
                security_id="41009",
                symbol=SYMBOL,
                side="SELL",
                order_type="MARKET",
                reason="FORCE_EXIT",
                quantity=65,
                limit_price=None,
                execution_mode="LIVE",
                status="CANCELLED",
                broker_name="DHAN",
                broker_order_id="S-X",
                filled_quantity=0,
                average_fill_price=None,
                created_at=OPENED_AT,
                submitted_at=OPENED_AT,
                updated_at=OPENED_AT,
            )
        )

        (
            _,
            entry_service,
            exit_service,
            _,
            _,
        ) = make_restorer(
            persistence
        )

        entry_any = cast(
            Any,
            entry_service,
        )

        exit_any = cast(
            Any,
            exit_service,
        )

        next_buy = (
            entry_any._next_intent_id(
                RECOVERY_AT
            )
        )

        next_sell = (
            exit_any._next_intent_id(
                RECOVERY_AT
            )
        )

        assert (
            next_buy.value
            == "ORD-20260810-000008"
        )

        assert (
            next_sell.value
            == "EXIT-20260810-000012"
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


# ============================================================
# Durable position rehydration
# ============================================================


def test_position_record_rehydrates_exact_m07_registry():
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        seed_runtime(
            persistence
        )

        seed_signal(
            persistence
        )

        seed_selection(
            persistence
        )

        seed_entry_order(
            persistence
        )

        seed_position(
            persistence
        )

        (
            restorer,
            _,
            _,
            _,
            registry,
        ) = make_restorer(
            persistence
        )

        position = (
            persistence
            .position_repository
            .require(
                POSITION_ID
            )
        )

        restorer.restore_position(
            persisted_position=position,
            broker_snapshot=(
                BrokerRecoveryPositionSnapshot(
                    security_id="41009",
                    net_quantity=65,
                    average_price=None,
                    checked_at=RECOVERY_AT,
                )
            ),
        )

        values = registry.all()

        assert len(values) == 1

        managed = values[0]

        assert (
            managed
            .position
            .position_id
            .value
            == POSITION_ID
        )

        assert managed.open_quantity == 65
        assert managed.closed_quantity == 0
        assert managed.stop_loss is not None
        assert managed.target is not None

        # Exact replay is idempotent.
        restorer.restore_position(
            persisted_position=position,
            broker_snapshot=(
                BrokerRecoveryPositionSnapshot(
                    security_id="41009",
                    net_quantity=65,
                    average_price=None,
                    checked_at=RECOVERY_AT,
                )
            ),
        )

        assert len(
            registry.all()
        ) == 1

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


# ============================================================
# BUY recovery
# ============================================================


def test_cancelled_unfilled_buy_restores_terminal_runtime_state():
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        seed_runtime(
            persistence
        )

        seed_signal(
            persistence
        )

        seed_entry_order(
            persistence,
            status="SUBMITTED",
            position_id=None,
        )

        (
            restorer,
            entry_service,
            _,
            _,
            _,
        ) = make_restorer(
            persistence
        )

        order = (
            persistence
            .order_repository
            .require(
                ENTRY_ORDER_ID
            )
        )

        restorer.restore_order(
            persisted_order=order,
            broker_snapshot=(
                BrokerRecoveryOrderSnapshot(
                    broker_order_id=(
                        "DHAN-ENTRY-001"
                    ),
                    state=(
                        BrokerRecoveryOrderState
                        .CANCELLED
                    ),
                    quantity=65,
                    filled_quantity=0,
                    average_fill_price=None,
                    checked_at=RECOVERY_AT,
                )
            ),
        )

        durable = (
            persistence
            .order_repository
            .require(
                ENTRY_ORDER_ID
            )
        )

        assert (
            durable.status
            == "CANCELLED"
        )

        state = (
            entry_service
            .order_state_machine
            .snapshot(
                cast(
                    Any,
                    ENTRY_ORDER_ID,
                )
            )
        ) if False else None

        # Inspect through recovery-safe owners without weakening
        # production types.
        entry_any = cast(
            Any,
            entry_service,
        )

        lifecycle = (
            entry_any
            .order_state_machine
            ._states[
                ENTRY_ORDER_ID
            ]
        )

        assert (
            lifecycle
            is OrderLifecycleState
            .CANCELLED
        )

        guard = (
            entry_service
            .idempotency_guard
        )

        key = (
            IdempotencyKey(
                value=(
                    f"SIGNAL:{SIGNAL_ID}"
                )
            )
        )

        assert (
            require_guard_record(guard, key).state
            is IdempotencyState.RELEASED
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_open_buy_recovery_fails_closed_without_resubmission():
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        seed_runtime(
            persistence
        )

        seed_signal(
            persistence
        )

        seed_entry_order(
            persistence,
            status="SUBMITTED",
            position_id=None,
        )

        (
            restorer,
            _,
            _,
            _,
            _,
        ) = make_restorer(
            persistence
        )

        order = (
            persistence
            .order_repository
            .require(
                ENTRY_ORDER_ID
            )
        )

        with pytest.raises(
            PhoenixRecoveryError,
            match="unresolved BUY",
        ):
            restorer.restore_order(
                persisted_order=order,
                broker_snapshot=(
                    BrokerRecoveryOrderSnapshot(
                        broker_order_id=(
                            "DHAN-ENTRY-001"
                        ),
                        state=(
                            BrokerRecoveryOrderState
                            .OPEN
                        ),
                        quantity=65,
                        filled_quantity=0,
                        average_fill_price=None,
                        checked_at=RECOVERY_AT,
                    )
                ),
            )

        durable = (
            persistence
            .order_repository
            .require(
                ENTRY_ORDER_ID
            )
        )

        assert durable.status == "SUBMITTED"

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_filled_buy_finalizes_only_with_existing_position_record():
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        seed_runtime(
            persistence
        )

        seed_signal(
            persistence
        )

        seed_selection(
            persistence
        )

        seed_entry_order(
            persistence,
            status="SUBMITTED",
            position_id=None,
        )

        seed_position(
            persistence
        )

        (
            restorer,
            entry_service,
            _,
            _,
            _,
        ) = make_restorer(
            persistence
        )

        order = (
            persistence
            .order_repository
            .require(
                ENTRY_ORDER_ID
            )
        )

        restorer.restore_order(
            persisted_order=order,
            broker_snapshot=(
                BrokerRecoveryOrderSnapshot(
                    broker_order_id=(
                        "DHAN-ENTRY-001"
                    ),
                    state=(
                        BrokerRecoveryOrderState
                        .FILLED
                    ),
                    quantity=65,
                    filled_quantity=65,
                    average_fill_price=100,
                    checked_at=RECOVERY_AT,
                )
            ),
        )

        durable = (
            persistence
            .order_repository
            .require(
                ENTRY_ORDER_ID
            )
        )

        assert durable.status == "FILLED"

        assert (
            durable.position_id
            == POSITION_ID
        )

        key = IdempotencyKey(
            value=(
                f"SIGNAL:{SIGNAL_ID}"
            )
        )

        assert (
            require_guard_record(entry_service.idempotency_guard, key).state
            is IdempotencyState.COMPLETED
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


# ============================================================
# SELL recovery
# ============================================================


def test_partial_sell_recovery_updates_fill_position_and_guard():
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        seed_runtime(
            persistence
        )

        seed_signal(
            persistence
        )

        seed_selection(
            persistence
        )

        seed_entry_order(
            persistence
        )

        seed_position(
            persistence
        )

        seed_sell_order(
            persistence
        )

        (
            restorer,
            _,
            _,
            exit_guard,
            registry,
        ) = make_restorer(
            persistence
        )

        sell = (
            persistence
            .order_repository
            .require(
                SELL_ORDER_ID
            )
        )

        restorer.restore_order(
            persisted_order=sell,
            broker_snapshot=(
                BrokerRecoveryOrderSnapshot(
                    broker_order_id=(
                        "DHAN-SELL-001"
                    ),
                    state=(
                        BrokerRecoveryOrderState
                        .PARTIALLY_FILLED
                    ),
                    quantity=65,
                    filled_quantity=30,
                    average_fill_price=126,
                    checked_at=RECOVERY_AT,
                )
            ),
        )

        durable_position = (
            persistence
            .position_repository
            .require(
                POSITION_ID
            )
        )

        assert (
            durable_position.open_quantity
            == 35
        )

        assert (
            durable_position.closed_quantity
            == 30
        )

        assert (
            durable_position.state
            == "EXIT_PENDING"
        )

        fills = (
            persistence
            .order_fill_repository
            .list_by_order(
                SELL_ORDER_ID
            )
        )

        assert len(fills) == 1
        assert fills[0].quantity == 30

        assert len(
            registry.all()
        ) == 1

        key = IdempotencyKey(
            value=(
                f"EXIT_POSITION:{POSITION_ID}"
            )
        )

        assert (
            require_guard_record(exit_guard, key).state
            is IdempotencyState.SUBMITTED
        )

        durable_sell = (
            persistence
            .order_repository
            .require(
                SELL_ORDER_ID
            )
        )

        # Broker lifecycle truth advances to PARTIALLY_FILLED,
        # but the SELL remains nonterminal/recovery-visible and
        # the position-level duplicate guard remains SUBMITTED.
        assert (
            durable_sell.status
            == "PARTIALLY_FILLED"
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_full_sell_recovery_closes_position_before_terminal_order():
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        seed_runtime(
            persistence
        )

        seed_signal(
            persistence
        )

        seed_selection(
            persistence
        )

        seed_entry_order(
            persistence
        )

        seed_position(
            persistence
        )

        seed_sell_order(
            persistence
        )

        (
            restorer,
            _,
            _,
            exit_guard,
            _,
        ) = make_restorer(
            persistence
        )

        sell = (
            persistence
            .order_repository
            .require(
                SELL_ORDER_ID
            )
        )

        restorer.restore_order(
            persisted_order=sell,
            broker_snapshot=(
                BrokerRecoveryOrderSnapshot(
                    broker_order_id=(
                        "DHAN-SELL-001"
                    ),
                    state=(
                        BrokerRecoveryOrderState
                        .FILLED
                    ),
                    quantity=65,
                    filled_quantity=65,
                    average_fill_price=128,
                    checked_at=RECOVERY_AT,
                )
            ),
        )

        durable_position = (
            persistence
            .position_repository
            .require(
                POSITION_ID
            )
        )

        durable_sell = (
            persistence
            .order_repository
            .require(
                SELL_ORDER_ID
            )
        )

        assert durable_position.open_quantity == 0
        assert durable_position.closed_quantity == 65
        assert durable_position.state == "CLOSED"

        assert durable_sell.status == "FILLED"
        assert durable_sell.filled_quantity == 65

        key = IdempotencyKey(
            value=(
                f"EXIT_POSITION:{POSITION_ID}"
            )
        )

        assert (
            require_guard_record(exit_guard, key).state
            is IdempotencyState.COMPLETED
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_cancelled_unfilled_sell_releases_position_and_guard():
    persistence = (
        build_persistence_foundation(
            config=(
                DatabaseConfig
                .sqlite_memory()
            )
        )
    )

    try:
        seed_runtime(
            persistence
        )

        seed_signal(
            persistence
        )

        seed_selection(
            persistence
        )

        seed_entry_order(
            persistence
        )

        seed_position(
            persistence,
            state="EXIT_PENDING",
        )

        seed_sell_order(
            persistence
        )

        (
            restorer,
            _,
            _,
            exit_guard,
            _,
        ) = make_restorer(
            persistence
        )

        sell = (
            persistence
            .order_repository
            .require(
                SELL_ORDER_ID
            )
        )

        restorer.restore_order(
            persisted_order=sell,
            broker_snapshot=(
                BrokerRecoveryOrderSnapshot(
                    broker_order_id=(
                        "DHAN-SELL-001"
                    ),
                    state=(
                        BrokerRecoveryOrderState
                        .CANCELLED
                    ),
                    quantity=65,
                    filled_quantity=0,
                    average_fill_price=None,
                    checked_at=RECOVERY_AT,
                )
            ),
        )

        durable_position = (
            persistence
            .position_repository
            .require(
                POSITION_ID
            )
        )

        durable_sell = (
            persistence
            .order_repository
            .require(
                SELL_ORDER_ID
            )
        )

        assert durable_position.open_quantity == 65
        assert durable_position.state == "OPEN"
        assert durable_sell.status == "CANCELLED"

        key = IdempotencyKey(
            value=(
                f"EXIT_POSITION:{POSITION_ID}"
            )
        )

        assert (
            require_guard_record(exit_guard, key).state
            is IdempotencyState.RELEASED
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
