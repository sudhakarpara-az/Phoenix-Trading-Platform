from datetime import timedelta

import pytest

from src.database.entry_durability import (
    TradingStatePersistenceError,
)
from src.execution.broker_execution_provider import (
    BrokerOrderSnapshot,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionResult,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
)

from tests.test_entry_durability import (
    LATER,
    make_intent,
    make_persistence,
    make_state_machine,
)


def build_cancelled_case():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        _,
        _,
        order_repository,
    ) = make_persistence()

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="BROKER-CANCEL-001",
    )

    result = ExecutionResult(
        intent_id=intent.intent_id,
        success=True,
        status=BrokerOrderStatus.OPEN,
        broker_reference=reference,
        submitted_at=LATER,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
    )

    cancelled_at = (
        LATER
        + timedelta(seconds=1)
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.CANCELLED,
        cancelled_at,
    )

    snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.CANCELLED,
        quantity=intent.quantity,
        filled_quantity=0,
        average_price=None,
        updated_at=cancelled_at,
    )

    return (
        persistence,
        order_repository,
        intent,
        result,
        machine,
        snapshot,
    )


def test_zero_fill_cancel_is_durable_terminal_state():
    (
        persistence,
        order_repository,
        intent,
        result,
        machine,
        snapshot,
    ) = build_cancelled_case()

    persistence.persist_cancelled_entry_order(
        intent=intent,
        result=result,
        broker_snapshot=snapshot,
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    durable = order_repository.get(
        intent.intent_id.value
    )

    assert durable is not None

    assert (
        durable.status
        == OrderLifecycleState.CANCELLED.value
    )

    assert durable.filled_quantity == 0
    assert durable.average_fill_price is None


def test_cancelled_checkpoint_is_idempotent():
    (
        persistence,
        order_repository,
        intent,
        result,
        machine,
        snapshot,
    ) = build_cancelled_case()

    lifecycle = machine.snapshot(
        intent.intent_id
    )

    persistence.persist_cancelled_entry_order(
        intent=intent,
        result=result,
        broker_snapshot=snapshot,
        lifecycle_snapshot=lifecycle,
    )

    persistence.persist_cancelled_entry_order(
        intent=intent,
        result=result,
        broker_snapshot=snapshot,
        lifecycle_snapshot=lifecycle,
    )

    durable = order_repository.get(
        intent.intent_id.value
    )

    assert durable is not None
    assert durable.status == "CANCELLED"


def test_nonzero_fill_cancel_cannot_be_terminalized():
    (
        persistence,
        order_repository,
        intent,
        result,
        machine,
        snapshot,
    ) = build_cancelled_case()

    partial = BrokerOrderSnapshot(
        broker_reference=(
            snapshot.broker_reference
        ),
        status=BrokerOrderStatus.CANCELLED,
        quantity=intent.quantity,
        filled_quantity=1,
        average_price=100.0,
        updated_at=snapshot.updated_at,
    )

    with pytest.raises(
        TradingStatePersistenceError,
        match="zero filled quantity",
    ):
        persistence.persist_cancelled_entry_order(
            intent=intent,
            result=result,
            broker_snapshot=partial,
            lifecycle_snapshot=(
                machine.snapshot(
                    intent.intent_id
                )
            ),
        )

    durable = order_repository.get(
        intent.intent_id.value
    )

    assert durable is not None

    assert (
        durable.status
        != OrderLifecycleState.CANCELLED.value
    )
