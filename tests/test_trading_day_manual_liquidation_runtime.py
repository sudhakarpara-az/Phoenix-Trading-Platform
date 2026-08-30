"""
M10 operator manual-liquidation tests.

These tests intentionally reuse the production-like durable SELL
test stack already used by the 15:15 force-exit runtime.
"""

from __future__ import annotations

from datetime import timedelta
from typing import (
    Any,
    cast,
)

from src.app.trading_day_runtime import (
    TradingDayForceExitRuntimeStatus,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
)
from src.execution.exit_execution_provider import (
    ExitOrderSnapshot,
)
from src.execution.position_exit_types import (
    ExitReason,
)
from src.risk.risk_types import (
    ManagedPositionState,
    RiskTriggerType,
)

from tests.test_exit_fill_durability import (
    BROKER_SELL_ID,
    FINAL_TIME,
    POSITION_ID,
    SELL_INTENT_ID,
    make_sell_intent,
    make_system,
    prepare_sell,
)
from tests.test_trading_day_force_exit_runtime import (
    RuntimeExitBroker,
    _runtime,
)


MANUAL_TIME = (
    FINAL_TIME
    + timedelta(seconds=10)
)


def _restore_open(
    *,
    lifecycle,
    registry,
    persistence,
):
    opened = (
        lifecycle
        .restore_after_reconciliation(
            position_id=(
                registry
                .all()[0]
                .position_id
            ),
            changed_at=FINAL_TIME,
        )
    )

    persistence.persist_managed_position_state(
        managed_position=opened
    )

    return opened


def test_manual_liquidation_submits_existing_durable_sell_path() -> None:
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
        _restore_open(
            lifecycle=lifecycle,
            registry=registry,
            persistence=persistence,
        )

        broker = RuntimeExitBroker()

        reference = BrokerOrderReference(
            broker_name="DHAN",
            order_id="DHAN-RUNTIME-SELL-1",
        )

        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=reference,
                status=BrokerOrderStatus.OPEN,
                quantity=65,
                filled_quantity=0,
                average_price=None,
                updated_at=MANUAL_TIME,
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

        results = (
            runtime
            .liquidate_open_positions(
                evaluated_at=MANUAL_TIME,
            )
        )

        assert len(results) == 1

        result = results[0]

        assert (
            result.instruction.trigger
            is RiskTriggerType.MANUAL
        )

        assert (
            result.status
            is TradingDayForceExitRuntimeStatus
            .LIVE_EXIT_ACTIVE
        )

        assert broker.submit_count == 1

        intent = (
            broker.submitted_intents[0]
        )

        assert (
            intent.reason
            is ExitReason.MANUAL
        )

        assert intent.quantity == 65

        managed = registry.all()[0]

        assert (
            managed.state
            is ManagedPositionState
            .EXIT_PENDING
        )

        durable = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable is not None
        assert durable.state == "EXIT_PENDING"
        assert durable.open_quantity == 65

    finally:
        sessions.stop()
        database.dispose()


def test_manual_liquidation_reconciles_existing_sell_before_replacement() -> None:
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
        old_intent = make_sell_intent()

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

        # Existing SELL is active.
        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=(
                    old_reference
                ),
                status=BrokerOrderStatus.OPEN,
                quantity=65,
                filled_quantity=0,
                average_price=None,
                updated_at=MANUAL_TIME,
            )
        )

        # Authoritative post-cancel state proves old SELL dead.
        cancelled_at = (
            MANUAL_TIME
            + timedelta(seconds=1)
        )

        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=(
                    old_reference
                ),
                status=(
                    BrokerOrderStatus.CANCELLED
                ),
                quantity=65,
                filled_quantity=0,
                average_price=None,
                updated_at=cancelled_at,
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

        # Immediate authoritative refresh of replacement SELL.
        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=(
                    replacement_reference
                ),
                status=BrokerOrderStatus.OPEN,
                quantity=65,
                filled_quantity=0,
                average_price=None,
                updated_at=(
                    cancelled_at
                    + timedelta(seconds=1)
                ),
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

        # Existing durable SELL consumed sequence 1.
        cast(
            Any,
            execution_service,
        )._sequence = 1

        results = (
            runtime
            .liquidate_open_positions(
                evaluated_at=MANUAL_TIME,
            )
        )

        assert len(results) == 1

        result = results[0]

        assert (
            result.instruction.trigger
            is RiskTriggerType.MANUAL
        )

        assert (
            result.status
            is TradingDayForceExitRuntimeStatus
            .REPLACEMENT_ACTIVE
        )

        assert broker.cancel_count == 1
        assert broker.submit_count == 1

        old_order = (
            order_repository.get(
                SELL_INTENT_ID
            )
        )

        assert old_order is not None
        assert old_order.status == "CANCELLED"

        replacement = (
            broker.submitted_intents[0]
        )

        assert (
            replacement.reason
            is ExitReason.MANUAL
        )

        assert replacement.quantity == 65

        durable = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable is not None
        assert durable.state == "EXIT_PENDING"
        assert durable.open_quantity == 65

    finally:
        sessions.stop()
        database.dispose()


def test_manual_liquidation_immediate_fill_closes_position() -> None:
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
        _restore_open(
            lifecycle=lifecycle,
            registry=registry,
            persistence=persistence,
        )

        broker = RuntimeExitBroker()

        reference = BrokerOrderReference(
            broker_name="DHAN",
            order_id="DHAN-RUNTIME-SELL-1",
        )

        broker.queue_status(
            ExitOrderSnapshot(
                broker_reference=reference,
                status=BrokerOrderStatus.FILLED,
                quantity=65,
                filled_quantity=65,
                average_price=130.0,
                updated_at=MANUAL_TIME,
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

        results = (
            runtime
            .liquidate_open_positions(
                evaluated_at=MANUAL_TIME,
            )
        )

        assert len(results) == 1

        assert (
            results[0].status
            is TradingDayForceExitRuntimeStatus
            .POSITION_CLOSED
        )

        assert (
            results[0].instruction.trigger
            is RiskTriggerType.MANUAL
        )

        assert broker.submit_count == 1

        assert (
            broker.submitted_intents[0].reason
            is ExitReason.MANUAL
        )

        managed = registry.all()[0]

        assert managed.open_quantity == 0

        assert (
            managed.state
            is ManagedPositionState.CLOSED
        )

        durable = (
            position_repository.get(
                POSITION_ID
            )
        )

        assert durable is not None
        assert durable.open_quantity == 0
        assert durable.state == "CLOSED"

    finally:
        sessions.stop()
        database.dispose()
