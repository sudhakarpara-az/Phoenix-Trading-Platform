"""
M10 actual 15:15 force-exit runtime integration tests.
"""

from __future__ import annotations

from datetime import datetime
from typing import (
    Any,
    cast,
)

from src.app.trading_day_runtime import (
    TradingDayForceExitRuntimeCoordinator,
    TradingDayForceExitRuntimeStatus,
)
from src.database.entry_durability import (
    DurableEntryBrokerExecutionProvider,
)
from src.database.exit_durability import (
    DurableExitExecutionProvider,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderIntent,
    ExitOrderSnapshot,
)
from src.execution.exit_execution_service import (
    ExitExecutionService,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.exit_reconciliation_service import (
    ExitReconciliationService,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
)
from src.execution.target_booking_policy import (
    TargetBookingPolicy,
)
from src.risk.force_exit_coordinator import (
    ForceExitCoordinator,
)
from src.risk.m06_exit_integration_service import (
    M07ToM06ExitIntegrationService,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.risk_types import (
    ManagedPositionState,
)
from src.services.scheduler import (
    TradingDayForceExitCoordinator,
    TradingDayScheduler,
)

from tests.test_exit_fill_durability import (
    BROKER_SELL_ID,
    ENTRY_TIME,
    EXIT_TIME,
    FINAL_TIME,
    POSITION_ID,
    SELL_INTENT_ID,
    TRADING_DATE,
    make_sell_intent,
    make_system,
    prepare_sell,
)


class RuntimeExitBroker(
    ExitExecutionProvider
):
    """
    Deterministic broker double supporting:

        submit SELL
        status refresh
        cancel
        final status refresh
    """

    def __init__(
        self,
    ) -> None:
        self.submit_count = 0
        self.cancel_count = 0
        self.status_count = 0

        self.submitted_intents: list[
            ExitOrderIntent
        ] = []

        self._status_queue: list[
            ExitOrderSnapshot
        ] = []

    @property
    def broker_name(
        self,
    ) -> str:
        return "DHAN"

    def queue_status(
        self,
        snapshot: ExitOrderSnapshot,
    ) -> None:
        self._status_queue.append(
            snapshot
        )

    def submit_exit(
        self,
        intent: ExitOrderIntent,
    ) -> ExitExecutionResult:
        self.submit_count += 1

        self.submitted_intents.append(
            intent
        )

        reference = BrokerOrderReference(
            broker_name="DHAN",
            order_id=(
                "DHAN-RUNTIME-SELL-"
                f"{self.submit_count}"
            ),
        )

        return ExitExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=reference,
            submitted_at=intent.created_at,
        )

    def cancel_exit(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> ExitCancellationResult:
        self.cancel_count += 1

        return ExitCancellationResult(
            broker_reference=(
                broker_reference
            ),
            success=True,
            status=(
                BrokerOrderStatus.CANCELLED
            ),
            cancelled_at=EXIT_TIME,
        )

    def get_exit_status(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> ExitOrderSnapshot:
        del broker_reference

        self.status_count += 1

        if not self._status_queue:
            raise AssertionError(
                "no queued broker status"
            )

        return self._status_queue.pop(
            0
        )


def _scheduler_boundary(
    registry,
) -> TradingDayForceExitCoordinator:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=datetime(
            2026,
            8,
            10,
            8,
            30,
        ),
    )

    scheduler.start(
        started_at=datetime(
            2026,
            8,
            10,
            9,
            15,
        )
    )

    return TradingDayForceExitCoordinator(
        scheduler=scheduler,
        force_exit_coordinator=(
            ForceExitCoordinator(
                registry=registry
            )
        ),
    )


def _runtime(
    *,
    persistence,
    order_repository,
    registry,
    lifecycle:
        PositionLifecycleManager,
    broker: RuntimeExitBroker,
):
    durable_provider = (
        DurableExitExecutionProvider(
            delegate=broker,
            persistence=persistence,
        )
    )

    guard = DuplicateOrderGuard()

    plan_builder = ExitPlanBuilder(
        TargetBookingPolicy()
    )

    execution_service = (
        ExitExecutionService(
            provider=durable_provider,
            duplicate_guard=guard,
            allow_live_exit_orders=True,
        )
    )

    integration = (
        M07ToM06ExitIntegrationService(
            registry=registry,
            lifecycle_manager=lifecycle,
            exit_plan_builder=(
                plan_builder
            ),
            exit_execution_service=(
                execution_service
            ),
        )
    )

    reconciliation = (
        ExitReconciliationService(
            provider=durable_provider,
            exit_plan_builder=(
                plan_builder
            ),
            duplicate_guard=guard,
        )
    )

    runtime = (
        TradingDayForceExitRuntimeCoordinator(
            trading_day_force_exit=(
                _scheduler_boundary(
                    registry
                )
            ),
            exit_integration=integration,
            exit_reconciliation=(
                reconciliation
            ),
            exit_persistence=(
                persistence
            ),
            durable_exit_provider=(
                durable_provider
            ),
            position_lifecycle_manager=(
                lifecycle
            ),
            position_registry=registry,
            order_repository=(
                order_repository
            ),
            duplicate_guard=guard,
            runtime_id="EXIT-RUNTIME",
            execution_mode=(
                ExecutionMode.LIVE
            ),
        )
    )

    return (
        runtime,
        execution_service,
    )


def test_new_force_exit_immediate_fill_closes_position_durably() -> None:
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
        # Test helper starts EXIT_PENDING.
        # Restore it so M07 emits NEW_FORCE_EXIT.
        opened = (
            lifecycle
            .restore_after_reconciliation(
                position_id=(
                    registry
                    .all()[0]
                    .position_id
                ),
                changed_at=EXIT_TIME,
            )
        )

        persistence.persist_managed_position_state(
            managed_position=opened
        )

        broker = RuntimeExitBroker()

        reference = BrokerOrderReference(
            broker_name="DHAN",
            order_id="DHAN-RUNTIME-SELL-1",
        )

        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=reference,
                status=(
                    BrokerOrderStatus.FILLED
                ),
                quantity=65,
                filled_quantity=65,
                average_price=128,
                updated_at=FINAL_TIME,
            )
        )

        runtime, _ = _runtime(
            persistence=persistence,
            order_repository=(
                order_repository
            ),
            registry=registry,
            lifecycle=lifecycle,
            broker=broker,
        )

        result = runtime.evaluate(
            evaluated_at=EXIT_TIME
        )

        assert (
            result.coordination.force_exit_due
            is True
        )

        assert len(
            result.instruction_results
        ) == 1

        instruction_result = (
            result.instruction_results[0]
        )

        assert (
            instruction_result.status
            is TradingDayForceExitRuntimeStatus
            .POSITION_CLOSED
        )

        managed = registry.all()[0]

        assert (
            managed.state
            is ManagedPositionState.CLOSED
        )

        assert managed.open_quantity == 0
        assert managed.closed_quantity == 65

        durable_position = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable_position is not None
        assert (
            durable_position.state
            == "CLOSED"
        )
        assert (
            durable_position.open_quantity
            == 0
        )

        fills = (
            fill_repository.list_by_order(
                instruction_result
                .exit_intent_id
                or ""
            )
        )

        assert sum(
            fill.quantity
            for fill in fills
        ) == 65

        sell = order_repository.get(
            instruction_result
            .exit_intent_id
            or ""
        )

        assert sell is not None
        assert sell.status == "FILLED"

        assert broker.submit_count == 1

    finally:
        sessions.stop()
        database.dispose()


def test_reconciliation_applies_fill_before_replacement_sell() -> None:
    (
        database,
        sessions,
        order_repository,
        _,
        position_repository,
        persistence,
        registry,
        lifecycle,
    ) = make_system()

    try:
        old_intent = (
            make_sell_intent()
        )

        prepare_sell(
            persistence,
            old_intent,
        )

        broker = RuntimeExitBroker()

        old_reference = (
            BrokerOrderReference(
                broker_name="DHAN",
                order_id=BROKER_SELL_ID,
            )
        )

        # Initial broker observation.
        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=(
                    old_reference
                ),
                status=(
                    BrokerOrderStatus
                    .PARTIALLY_FILLED
                ),
                quantity=65,
                filled_quantity=10,
                average_price=126,
                updated_at=EXIT_TIME,
            )
        )

        # Final post-cancel broker observation.
        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=(
                    old_reference
                ),
                status=(
                    BrokerOrderStatus.CANCELLED
                ),
                quantity=65,
                filled_quantity=15,
                average_price=126,
                updated_at=FINAL_TIME,
            )
        )

        replacement_reference = (
            BrokerOrderReference(
                broker_name="DHAN",
                order_id=(
                    "DHAN-RUNTIME-SELL-1"
                ),
            )
        )

        # Immediate replacement refresh.
        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=(
                    replacement_reference
                ),
                status=BrokerOrderStatus.OPEN,
                quantity=50,
                filled_quantity=0,
                average_price=None,
                updated_at=FINAL_TIME,
            )
        )

        runtime, execution_service = (
            _runtime(
                persistence=persistence,
                order_repository=(
                    order_repository
                ),
                registry=registry,
                lifecycle=lifecycle,
                broker=broker,
            )
        )

        # Existing durable SELL is sequence 1.
        # Replacement must receive a distinct sequence 2.
        cast(
            Any,
            execution_service,
        )._sequence = 1

        result = runtime.evaluate(
            evaluated_at=EXIT_TIME
        )

        assert len(
            result.instruction_results
        ) == 1

        instruction_result = (
            result.instruction_results[0]
        )

        assert (
            instruction_result.status
            is TradingDayForceExitRuntimeStatus
            .REPLACEMENT_ACTIVE
        )

        old_order = (
            order_repository.get(
                SELL_INTENT_ID
            )
        )

        assert old_order is not None

        # Old SELL is durably dead before replacement remains
        # active.
        assert (
            old_order.status
            == "CANCELLED"
        )

        durable_position = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable_position is not None

        # 15 broker-confirmed units crossed M07 + DB before
        # replacement SELL.
        assert (
            durable_position.closed_quantity
            == 15
        )

        assert (
            durable_position.open_quantity
            == 50
        )

        assert (
            durable_position.state
            == "EXIT_PENDING"
        )

        assert broker.cancel_count == 1
        assert broker.submit_count == 1

        replacement = (
            broker.submitted_intents[0]
        )

        assert replacement.quantity == 50

        assert (
            replacement.created_at
            == FINAL_TIME
        )

        replacement_record = (
            order_repository.get(
                replacement.intent_id.value
            )
        )

        assert replacement_record is not None

        assert (
            replacement_record.status
            == "OPEN"
        )

        assert (
            replacement_record.quantity
            == 50
        )

    finally:
        sessions.stop()
        database.dispose()


def test_missing_durable_sell_fails_closed_without_new_sell() -> None:
    (
        database,
        sessions,
        order_repository,
        _,
        position_repository,
        persistence,
        registry,
        lifecycle,
    ) = make_system()

    try:
        broker = RuntimeExitBroker()

        runtime, _ = _runtime(
            persistence=persistence,
            order_repository=(
                order_repository
            ),
            registry=registry,
            lifecycle=lifecycle,
            broker=broker,
        )

        # Registry position is EXIT_PENDING but no durable SELL
        # has been created.
        result = runtime.evaluate(
            evaluated_at=EXIT_TIME
        )

        instruction_result = (
            result.instruction_results[0]
        )

        assert (
            instruction_result.status
            is TradingDayForceExitRuntimeStatus
            .RECONCILIATION_REQUIRED
        )

        assert broker.submit_count == 0
        assert broker.cancel_count == 0
        assert broker.status_count == 0

        managed = registry.all()[0]

        assert (
            managed.state
            is ManagedPositionState
            .RECONCILIATION_REQUIRED
        )

        durable = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable is not None

        assert (
            durable.state
            == "RECONCILIATION_REQUIRED"
        )

    finally:
        sessions.stop()
        database.dispose()
