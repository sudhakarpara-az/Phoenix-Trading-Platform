"""
Crash-safe SELL fill and PositionRecord durability tests.
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
from src.database.exit_durability import (
    ExitStatePersistenceError,
    SQLAlchemyExitPersistenceService,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyOrderFillRepository,
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
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    OrderIntentId,
)
from src.execution.exit_execution_provider import (
    ExitExecutionResult,
    ExitOrderIntent,
    ExitOrderIntentId,
    ExitOrderSnapshot,
    ExitTransactionType,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitReason,
    FilledPosition,
    FilledPositionId,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    StopLossDefinition,
    TargetDefinition,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

EXPIRY = date(
    2026,
    8,
    11,
)

ENTRY_TIME = datetime(
    2026,
    8,
    10,
    9,
    30,
)

EXIT_TIME = datetime(
    2026,
    8,
    10,
    15,
    15,
)

PARTIAL_TIME = (
    EXIT_TIME
    + timedelta(seconds=1)
)

FINAL_TIME = (
    EXIT_TIME
    + timedelta(seconds=2)
)

SYMBOL = (
    "NIFTY50-20260811-24450-CE"
)

POSITION_ID = (
    "POS-20260810-000001"
)

ENTRY_INTENT_ID = (
    "ENTRY-001"
)

SELL_INTENT_ID = (
    "EXIT-20260810-000001"
)

BROKER_SELL_ID = (
    "DHAN-SELL-001"
)


def make_option() -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol=(
                    "NIFTY 50"
                ),
                symbol=SYMBOL,
                security_id="41009",
                option_type=(
                    OptionType.CALL
                ),
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=100,
                bid=99.95,
                ask=100.05,
                volume=1000,
                open_interest=50000,
                received_at=ENTRY_TIME,
            ),
            greeks=OptionGreeks(
                delta=0.64,
                calculated_at=ENTRY_TIME,
            ),
        ),
        selected_at=ENTRY_TIME,
        selection_delta_target=0.64,
    )


def make_managed_position() -> ManagedPosition:
    filled = FilledPosition(
        position_id=FilledPositionId(
            POSITION_ID
        ),
        signal_id=SignalId(
            "SIG-001"
        ),
        entry_intent_id=OrderIntentId(
            ENTRY_INTENT_ID
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id=(
                    "DHAN-ENTRY-001"
                ),
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=65,
        entry_price=100,
        filled_at=ENTRY_TIME,
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            f"RISK:{POSITION_ID}"
        ),
        position=filled,
        open_quantity=65,
        closed_quantity=0,
        realized_pnl=0,
        state=(
            ManagedPositionState
            .EXIT_PENDING
        ),
        stop_loss=StopLossDefinition(
            stop_price=85,
            risk_points=15,
        ),
        target=TargetDefinition(
            executable_price=127,
            mapped_target_price=130,
            booking_zone_start=127,
            booking_zone_end=130,
        ),
        created_at=ENTRY_TIME,
        updated_at=EXIT_TIME,
    )


def make_sell_intent() -> ExitOrderIntent:
    return ExitOrderIntent(
        intent_id=ExitOrderIntentId(
            SELL_INTENT_ID
        ),
        position_id=FilledPositionId(
            POSITION_ID
        ),
        security_id="41009",
        symbol=SYMBOL,
        option_type=OptionType.CALL,
        transaction_type=(
            ExitTransactionType.SELL
        ),
        order_type=ExitOrderType.MARKET,
        quantity=65,
        price=None,
        reason=ExitReason.FORCE_EXIT,
        created_at=EXIT_TIME,
    )


def make_system():
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

    runtime_repository = (
        SQLAlchemyRuntimeSessionRepository(
            sessions=sessions
        )
    )

    signal_repository = (
        SQLAlchemySignalRepository(
            sessions=sessions
        )
    )

    order_repository = (
        SQLAlchemyOrderRepository(
            sessions=sessions
        )
    )

    fill_repository = (
        SQLAlchemyOrderFillRepository(
            sessions=sessions
        )
    )

    position_repository = (
        SQLAlchemyPositionRepository(
            sessions=sessions
        )
    )

    runtime_repository.add(
        RuntimeSessionRecord(
            runtime_id="EXIT-RUNTIME",
            trading_date=TRADING_DATE,
            mode="LIVE",
            state="RUNNING",
            started_at=ENTRY_TIME,
            updated_at=EXIT_TIME,
            recovery_required=False,
            recovered=False,
        )
    )

    signal_repository.add(
        SignalRecord(
            signal_id="SIG-001",
            runtime_id="EXIT-RUNTIME",
            trading_date=TRADING_DATE,
            level="K5",
            signal_type="BUY_CALL",
            option_type="CALL",
            underlying_price=24600,
            quantity=65,
            status="CREATED",
            reason="K5 trigger",
            created_at=ENTRY_TIME,
            updated_at=ENTRY_TIME,
        )
    )

    order_repository.add(
        OrderRecord(
            order_intent_id=(
                ENTRY_INTENT_ID
            ),
            runtime_id="EXIT-RUNTIME",
            signal_id="SIG-001",
            position_id=POSITION_ID,
            security_id="41009",
            symbol=SYMBOL,
            side="BUY",
            order_type="LIMIT",
            reason="K5",
            quantity=65,
            limit_price=100,
            execution_mode="LIVE",
            status="FILLED",
            broker_name="DHAN",
            broker_order_id=(
                "DHAN-ENTRY-001"
            ),
            filled_quantity=65,
            average_fill_price=100,
            created_at=ENTRY_TIME,
            submitted_at=ENTRY_TIME,
            updated_at=ENTRY_TIME,
        )
    )

    position_repository.add(
        PositionRecord(
            position_id=POSITION_ID,
            risk_id=(
                f"RISK:{POSITION_ID}"
            ),
            runtime_id="EXIT-RUNTIME",
            signal_id="SIG-001",
            entry_order_intent_id=(
                ENTRY_INTENT_ID
            ),
            security_id="41009",
            symbol=SYMBOL,
            option_type="CALL",
            level="K5",
            original_quantity=65,
            open_quantity=65,
            closed_quantity=0,
            entry_price=100,
            realized_pnl=0,
            state="OPEN",
            stop_price=85,
            stop_risk_points=15,
            stop_state="ARMED",
            executable_target_price=127,
            mapped_target_price=130,
            booking_zone_start=127,
            booking_zone_end=130,
            target_state="ARMED",
            opened_at=ENTRY_TIME,
            updated_at=ENTRY_TIME,
            closed_at=None,
        )
    )

    persistence = (
        SQLAlchemyExitPersistenceService(
            runtime_id="EXIT-RUNTIME",
            order_repository=(
                order_repository
            ),
            fill_repository=(
                fill_repository
            ),
            position_repository=(
                position_repository
            ),
        )
    )

    registry = PositionRegistry()

    managed = make_managed_position()

    registry.register(
        managed
    )

    lifecycle = (
        PositionLifecycleManager(
            registry=registry
        )
    )

    return (
        database,
        sessions,
        order_repository,
        fill_repository,
        position_repository,
        persistence,
        registry,
        lifecycle,
    )


def prepare_sell(
    persistence:
        SQLAlchemyExitPersistenceService,
    intent: ExitOrderIntent,
) -> BrokerOrderReference:
    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id=BROKER_SELL_ID,
    )

    persistence.persist_broker_submission_result(
        intent=intent,
        result=ExitExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=reference,
            submitted_at=EXIT_TIME,
        ),
    )

    return reference


def make_partial_snapshot(
    reference: BrokerOrderReference,
) -> ExitOrderSnapshot:
    return ExitOrderSnapshot(
        broker_reference=reference,
        status=(
            BrokerOrderStatus
            .PARTIALLY_FILLED
        ),
        quantity=65,
        filled_quantity=30,
        average_price=126,
        updated_at=PARTIAL_TIME,
    )


def make_final_snapshot(
    reference: BrokerOrderReference,
) -> ExitOrderSnapshot:
    average = (
        (
            30 * 126
            + 35 * 128
        )
        / 65
    )

    return ExitOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=65,
        filled_quantity=65,
        average_price=average,
        updated_at=FINAL_TIME,
    )


def test_partial_then_full_sell_is_crash_safe() -> None:
    (
        database,
        sessions,
        order_repository,
        fill_repository,
        position_repository,
        persistence,
        registry,
        lifecycle,
    ) = make_system()

    try:
        intent = make_sell_intent()

        reference = prepare_sell(
            persistence,
            intent,
        )

        partial = make_partial_snapshot(
            reference
        )

        delta = (
            persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=partial,
            )
        )

        assert delta.quantity == 30
        assert delta.price == pytest.approx(
            126
        )

        fills = (
            fill_repository.list_by_order(
                SELL_INTENT_ID
            )
        )

        assert len(fills) == 1
        assert fills[0].quantity == 30
        assert fills[0].price == (
            pytest.approx(126)
        )

        # Fill ledger is durable BEFORE PositionRecord changes.
        durable_before = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable_before is not None
        assert (
            durable_before.open_quantity
            == 65
        )
        assert (
            durable_before.closed_quantity
            == 0
        )

        assert delta.price is not None

        managed = (
            lifecycle.apply_exit_fill(
                position_id=FilledPositionId(
                    POSITION_ID
                ),
                fill_quantity=(
                    delta.quantity
                ),
                fill_price=delta.price,
                filled_at=delta.filled_at,
            )
        )

        persistence.persist_managed_position_after_snapshot(
            intent=intent,
            snapshot=partial,
            managed_position=managed,
        )

        durable_partial = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable_partial is not None
        assert (
            durable_partial.open_quantity
            == 35
        )
        assert (
            durable_partial.closed_quantity
            == 30
        )
        assert (
            durable_partial.realized_pnl
            == pytest.approx(780)
        )
        assert (
            durable_partial.state
            == "PARTIALLY_EXITED"
        )

        partial_order = (
            order_repository.get(
                SELL_INTENT_ID
            )
        )

        assert partial_order is not None

        assert (
            partial_order.status
            == "PARTIALLY_FILLED"
        )

        # Replay of exact same broker state cannot double-apply.
        replay = (
            persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=partial,
            )
        )

        assert replay.quantity == 0
        assert replay.price is None

        final = make_final_snapshot(
            reference
        )

        final_delta = (
            persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=final,
            )
        )

        assert final_delta.quantity == 35

        assert (
            final_delta.price
            == pytest.approx(128)
        )

        # Broker is FILLED, but durable SELL must still remain
        # unresolved until PositionRecord is CLOSED.
        before_terminal = (
            order_repository.get(
                SELL_INTENT_ID
            )
        )

        assert before_terminal is not None
        assert (
            before_terminal.status
            != "FILLED"
        )

        assert final_delta.price is not None

        closed = (
            lifecycle.apply_exit_fill(
                position_id=FilledPositionId(
                    POSITION_ID
                ),
                fill_quantity=(
                    final_delta.quantity
                ),
                fill_price=(
                    final_delta.price
                ),
                filled_at=(
                    final_delta.filled_at
                ),
            )
        )

        persistence.persist_managed_position_after_snapshot(
            intent=intent,
            snapshot=final,
            managed_position=closed,
        )

        durable_closed = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable_closed is not None
        assert (
            durable_closed.open_quantity
            == 0
        )
        assert (
            durable_closed.closed_quantity
            == 65
        )
        assert (
            durable_closed.realized_pnl
            == pytest.approx(1760)
        )
        assert (
            durable_closed.state
            == "CLOSED"
        )
        assert (
            durable_closed.closed_at
            == FINAL_TIME
        )

        terminal_order = (
            order_repository.get(
                SELL_INTENT_ID
            )
        )

        assert terminal_order is not None
        assert (
            terminal_order.status
            == "FILLED"
        )
        assert (
            terminal_order.filled_quantity
            == 65
        )

        unresolved = (
            order_repository.list_open_orders(
                "EXIT-RUNTIME"
            )
        )

        assert all(
            record.order_intent_id
            != SELL_INTENT_ID
            for record in unresolved
        )

        fills = (
            fill_repository.list_by_order(
                SELL_INTENT_ID
            )
        )

        assert len(fills) == 2
        assert sum(
            fill.quantity
            for fill in fills
        ) == 65

        assert (
            registry.require(
                FilledPositionId(
                    POSITION_ID
                )
            ).state
            is ManagedPositionState.CLOSED
        )

    finally:
        sessions.stop()
        database.dispose()


def test_fill_ledger_replays_after_crash_before_position_update() -> None:
    (
        database,
        sessions,
        _,
        fill_repository,
        position_repository,
        persistence,
        _,
        _,
    ) = make_system()

    try:
        intent = make_sell_intent()

        reference = prepare_sell(
            persistence,
            intent,
        )

        partial = make_partial_snapshot(
            reference
        )

        first = (
            persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=partial,
            )
        )

        assert first.quantity == 30

        # Simulated crash:
        #
        # We intentionally DO NOT call M07 apply_exit_fill()
        # and DO NOT persist PositionRecord.
        #
        # Replaying same broker snapshot must rediscover all
        # 30 unapplied contracts from durable fill ledger.
        replay = (
            persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=partial,
            )
        )

        assert replay.quantity == 30
        assert (
            replay.price
            == pytest.approx(126)
        )

        fills = (
            fill_repository.list_by_order(
                SELL_INTENT_ID
            )
        )

        assert len(fills) == 1
        assert fills[0].quantity == 30

        durable_position = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable_position is not None
        assert (
            durable_position.open_quantity
            == 65
        )
        assert (
            durable_position.closed_quantity
            == 0
        )

    finally:
        sessions.stop()
        database.dispose()


def test_terminal_broker_fill_stays_recovery_visible_until_position_is_durable() -> None:
    (
        database,
        sessions,
        order_repository,
        fill_repository,
        position_repository,
        persistence,
        _,
        _,
    ) = make_system()

    try:
        intent = make_sell_intent()

        reference = prepare_sell(
            persistence,
            intent,
        )

        final = ExitOrderSnapshot(
            broker_reference=reference,
            status=(
                BrokerOrderStatus.FILLED
            ),
            quantity=65,
            filled_quantity=65,
            average_price=128,
            updated_at=FINAL_TIME,
        )

        delta = (
            persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=final,
            )
        )

        assert delta.quantity == 65
        assert (
            delta.price
            == pytest.approx(128)
        )

        fills = (
            fill_repository.list_by_order(
                SELL_INTENT_ID
            )
        )

        assert len(fills) == 1
        assert fills[0].quantity == 65

        position = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert position is not None

        # Position transaction has not occurred yet.
        assert position.open_quantity == 65
        assert position.closed_quantity == 0

        order = order_repository.get(
            SELL_INTENT_ID
        )

        assert order is not None

        # Critical invariant:
        # broker terminal != durable Phoenix terminal yet.
        assert order.status != "FILLED"

        unresolved = (
            order_repository.list_open_orders(
                "EXIT-RUNTIME"
            )
        )

        assert any(
            record.order_intent_id
            == SELL_INTENT_ID
            for record in unresolved
        )

    finally:
        sessions.stop()
        database.dispose()


def test_position_quantity_mismatch_cannot_terminalize_sell() -> None:
    (
        database,
        sessions,
        order_repository,
        _,
        position_repository,
        persistence,
        _,
        lifecycle,
    ) = make_system()

    try:
        intent = make_sell_intent()

        reference = prepare_sell(
            persistence,
            intent,
        )

        partial = make_partial_snapshot(
            reference
        )

        delta = (
            persistence
            .checkpoint_broker_snapshot(
                intent=intent,
                snapshot=partial,
            )
        )

        assert delta.quantity == 30

        # Deliberately apply less than broker-confirmed quantity.
        wrong_managed = (
            lifecycle.apply_exit_fill(
                position_id=FilledPositionId(
                    POSITION_ID
                ),
                fill_quantity=20,
                fill_price=126,
                filled_at=PARTIAL_TIME,
            )
        )

        with pytest.raises(
            ExitStatePersistenceError,
            match=(
                "managed position quantities do not "
                "reflect broker SELL snapshot"
            ),
        ):
            persistence.persist_managed_position_after_snapshot(
                intent=intent,
                snapshot=partial,
                managed_position=(
                    wrong_managed
                ),
            )

        durable_position = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable_position is not None

        # Invalid M07 state never crossed the DB boundary.
        assert durable_position.open_quantity == 65
        assert durable_position.closed_quantity == 0

        order = order_repository.get(
            SELL_INTENT_ID
        )

        assert order is not None
        assert order.status != "FILLED"

    finally:
        sessions.stop()
        database.dispose()


def test_managed_lifecycle_state_can_be_persisted_without_terminalizing_sell() -> None:
    (
        database,
        sessions,
        order_repository,
        _,
        position_repository,
        persistence,
        _,
        lifecycle,
    ) = make_system()

    try:
        intent = make_sell_intent()

        prepare_sell(
            persistence,
            intent,
        )

        managed = (
            lifecycle
            .mark_reconciliation_required(
                position_id=(
                    FilledPositionId(
                        POSITION_ID
                    )
                ),
                changed_at=FINAL_TIME,
            )
        )

        persistence.persist_managed_position_state(
            managed_position=managed
        )

        durable_position = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable_position is not None

        assert (
            durable_position.state
            == "RECONCILIATION_REQUIRED"
        )

        assert (
            durable_position.open_quantity
            == 65
        )

        sell_order = (
            order_repository.get(
                SELL_INTENT_ID
            )
        )

        assert sell_order is not None

        # Position-state durability never guesses terminal
        # broker order state.
        assert (
            sell_order.status
            == "SUBMITTED"
        )

    finally:
        sessions.stop()
        database.dispose()
