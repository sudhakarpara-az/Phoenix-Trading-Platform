"""
Crash-safe SELL persistence tests.
"""

from datetime import (
    date,
    datetime,
)

import pytest

from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.exit_durability import (
    DurableExitExecutionProvider,
    ExitStatePersistenceError,
    SQLAlchemyExitPersistenceService,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyOrderRepository,
    SQLAlchemyRuntimeSessionRepository,
)
from src.database.schema import (
    RuntimeSessionRecord,
    create_schema,
)
from src.database.session import (
    DatabaseSessionManager,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderIntent,
    ExitOrderIntentId,
    ExitOrderSnapshot,
    ExitTransactionType,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitReason,
    FilledPositionId,
)
from src.option_selection.option_types import (
    OptionType,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

NOW = datetime(
    2026,
    8,
    10,
    15,
    15,
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

    runtime_repository = (
        SQLAlchemyRuntimeSessionRepository(
            sessions=sessions
        )
    )

    order_repository = (
        SQLAlchemyOrderRepository(
            sessions=sessions
        )
    )

    runtime_repository.add(
        RuntimeSessionRecord(
            runtime_id="EXIT-RUNTIME",
            trading_date=TRADING_DATE,
            mode="LIVE",
            state="RUNNING",
            started_at=NOW,
            updated_at=NOW,
            recovery_required=False,
            recovered=False,
        )
    )

    persistence = (
        SQLAlchemyExitPersistenceService(
            runtime_id="EXIT-RUNTIME",
            order_repository=order_repository,
        )
    )

    return (
        database,
        sessions,
        order_repository,
        persistence,
    )


def make_intent() -> ExitOrderIntent:
    return ExitOrderIntent(
        intent_id=ExitOrderIntentId(
            "EXIT-20260810-000001"
        ),
        position_id=FilledPositionId(
            "POS-20260810-000001"
        ),
        security_id="41009",
        symbol="NIFTY-CE",
        option_type=OptionType.CALL,
        transaction_type=(
            ExitTransactionType.SELL
        ),
        order_type=ExitOrderType.MARKET,
        quantity=65,
        price=None,
        reason=ExitReason.FORCE_EXIT,
        created_at=NOW,
    )


class FakeExitProvider(
    ExitExecutionProvider
):
    def __init__(
        self,
        *,
        order_repository:
            SQLAlchemyOrderRepository,
        result_status:
            BrokerOrderStatus = (
                BrokerOrderStatus.OPEN
            ),
        result_success: bool = True,
    ) -> None:
        self._order_repository = (
            order_repository
        )

        self._result_status = (
            result_status
        )

        self._result_success = (
            result_success
        )

        self.submit_count = 0

    @property
    def broker_name(
        self,
    ) -> str:
        return "DHAN"

    def submit_exit(
        self,
        intent: ExitOrderIntent,
    ) -> ExitExecutionResult:
        self.submit_count += 1

        # Durability must exist before broker call.
        durable = (
            self._order_repository.get(
                intent.intent_id.value
            )
        )

        assert durable is not None
        assert durable.side == "SELL"
        assert durable.status == "SUBMITTED"
        assert (
            durable.broker_order_id
            is None
        )

        reference = (
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="DHAN-SELL-001",
            )
            if self._result_success
            else None
        )

        return ExitExecutionResult(
            intent_id=intent.intent_id,
            success=self._result_success,
            status=self._result_status,
            broker_reference=reference,
            submitted_at=NOW,
            message=(
                None
                if self._result_success
                else "broker state uncertain"
            ),
        )

    def cancel_exit(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> ExitCancellationResult:
        raise AssertionError(
            "cancel_exit not expected"
        )

    def get_exit_status(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> ExitOrderSnapshot:
        raise AssertionError(
            "get_exit_status not expected"
        )


def test_sell_intent_is_durable_before_broker() -> None:
    (
        database,
        sessions,
        order_repository,
        persistence,
    ) = make_runtime()

    try:
        intent = make_intent()

        persistence.persist_pre_broker_submission(
            intent=intent,
            broker_name="DHAN",
        )

        record = order_repository.get(
            intent.intent_id.value
        )

        assert record is not None

        assert record.runtime_id == (
            "EXIT-RUNTIME"
        )

        assert record.signal_id is None

        assert record.position_id == (
            intent.position_id.value
        )

        assert record.side == "SELL"

        assert record.order_type == (
            "MARKET"
        )

        assert record.reason == (
            "FORCE_EXIT"
        )

        assert record.execution_mode == (
            "LIVE"
        )

        assert record.status == (
            "SUBMITTED"
        )

        assert (
            record.broker_order_id
            is None
        )

    finally:
        sessions.stop()
        database.dispose()


def test_durable_provider_persists_before_delegate() -> None:
    (
        database,
        sessions,
        order_repository,
        persistence,
    ) = make_runtime()

    try:
        delegate = FakeExitProvider(
            order_repository=(
                order_repository
            )
        )

        provider = (
            DurableExitExecutionProvider(
                delegate=delegate,
                persistence=persistence,
            )
        )

        intent = make_intent()

        result = provider.submit_exit(
            intent
        )

        assert result.success is True
        assert delegate.submit_count == 1

        record = order_repository.get(
            intent.intent_id.value
        )

        assert record is not None

        assert record.status == (
            "SUBMITTED"
        )

        assert record.broker_name == (
            "DHAN"
        )

        assert record.broker_order_id == (
            "DHAN-SELL-001"
        )

        open_orders = (
            order_repository
            .list_open_orders(
                "EXIT-RUNTIME"
            )
        )

        assert any(
            open_order.order_intent_id
            == record.order_intent_id
            for open_order
            in open_orders
        )

    finally:
        sessions.stop()
        database.dispose()


def test_durable_sell_replay_is_blocked_before_broker() -> None:
    (
        database,
        sessions,
        order_repository,
        persistence,
    ) = make_runtime()

    try:
        delegate = FakeExitProvider(
            order_repository=(
                order_repository
            )
        )

        provider = (
            DurableExitExecutionProvider(
                delegate=delegate,
                persistence=persistence,
            )
        )

        intent = make_intent()

        provider.submit_exit(
            intent
        )

        with pytest.raises(
            ExitStatePersistenceError,
            match=(
                "durable SELL order already exists"
            ),
        ):
            provider.submit_exit(
                intent
            )

        assert delegate.submit_count == 1

    finally:
        sessions.stop()
        database.dispose()


def test_unknown_sell_result_stays_recovery_visible() -> None:
    (
        database,
        sessions,
        order_repository,
        persistence,
    ) = make_runtime()

    try:
        delegate = FakeExitProvider(
            order_repository=(
                order_repository
            ),
            result_status=(
                BrokerOrderStatus.UNKNOWN
            ),
            result_success=False,
        )

        provider = (
            DurableExitExecutionProvider(
                delegate=delegate,
                persistence=persistence,
            )
        )

        intent = make_intent()

        result = provider.submit_exit(
            intent
        )

        assert result.success is False

        record = order_repository.get(
            intent.intent_id.value
        )

        assert record is not None

        assert record.status == (
            "SUBMITTED"
        )

        assert (
            record.broker_order_id
            is None
        )

        unresolved = (
            order_repository
            .list_open_orders(
                "EXIT-RUNTIME"
            )
        )

        assert any(
            open_order.order_intent_id
            == record.order_intent_id
            for open_order
            in unresolved
        )

    finally:
        sessions.stop()
        database.dispose()
