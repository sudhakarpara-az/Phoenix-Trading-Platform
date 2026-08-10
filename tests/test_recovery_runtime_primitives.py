
"""
M10 recovery-safe in-memory runtime primitive tests.
"""

from datetime import (
    datetime,
    timedelta,
)
from threading import RLock
from typing import (
    Any,
    cast,
)

import pytest

from src.execution.execution_service import (
    ExecutionService,
)
from src.execution.execution_types import (
    OrderIntentId,
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


NOW = datetime(
    2026,
    8,
    10,
    10,
    0,
)


def test_duplicate_guard_restore_is_idempotent() -> None:
    guard = DuplicateOrderGuard()

    record = IdempotencyRecord(
        key=IdempotencyKey(
            value="ENTRY:SIG-RECOVERY"
        ),
        state=IdempotencyState.SUBMITTED,
        intent_id=(
            "ORD-20260810-000007"
        ),
        created_at=NOW,
        updated_at=NOW,
    )

    first = guard.restore_record(
        record
    )

    second = guard.restore_record(
        record
    )

    assert first == record
    assert second == record

    assert (
        guard.get(
            record.key
        )
        == record
    )

    assert (
        guard.is_blocked(
            record.key
        )
        is True
    )


def test_duplicate_guard_conflicting_restore_fails_closed():
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        value="EXIT_POSITION:POS-001"
    )

    guard.restore_record(
        IdempotencyRecord(
            key=key,
            state=(
                IdempotencyState.SUBMITTED
            ),
            intent_id=(
                "EXIT-20260810-000003"
            ),
            created_at=NOW,
            updated_at=NOW,
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "conflicting idempotency "
            "recovery state"
        ),
    ):
        guard.restore_record(
            IdempotencyRecord(
                key=key,
                state=(
                    IdempotencyState.COMPLETED
                ),
                intent_id=(
                    "EXIT-20260810-000003"
                ),
                created_at=NOW,
                updated_at=(
                    NOW
                    + timedelta(
                        seconds=1
                    )
                ),
            )
        )


def test_order_state_machine_restores_exact_snapshot():
    machine = OrderStateMachine()

    intent_id = OrderIntentId(
        "ORD-20260810-000007"
    )

    updated_at = (
        NOW
        + timedelta(
            seconds=5
        )
    )

    snapshot = machine.restore_state(
        intent_id=intent_id,
        current_state=(
            OrderLifecycleState.OPEN
        ),
        created_at=NOW,
        updated_at=updated_at,
    )

    assert (
        snapshot.current_state
        is OrderLifecycleState.OPEN
    )

    assert snapshot.created_at == NOW
    assert snapshot.updated_at == updated_at
    assert snapshot.transition_count == 0

    replay = machine.restore_state(
        intent_id=intent_id,
        current_state=(
            OrderLifecycleState.OPEN
        ),
        created_at=NOW,
        updated_at=updated_at,
    )

    assert replay == snapshot

    assert (
        machine.get_state(
            intent_id
        )
        is OrderLifecycleState.OPEN
    )


def test_order_state_machine_conflicting_restore_fails():
    machine = OrderStateMachine()

    intent_id = OrderIntentId(
        "ORD-20260810-000008"
    )

    machine.restore_state(
        intent_id=intent_id,
        current_state=(
            OrderLifecycleState.SUBMITTED
        ),
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "conflicting order lifecycle "
            "recovery state"
        ),
    ):
        machine.restore_state(
            intent_id=intent_id,
            current_state=(
                OrderLifecycleState.FILLED
            ),
            created_at=NOW,
            updated_at=NOW,
        )


def test_buy_sequence_floor_is_monotonic() -> None:
    service = cast(
        Any,
        object.__new__(
            ExecutionService
        ),
    )

    service._sequence = 0
    service._sequence_lock = RLock()

    assert (
        service.restore_sequence_floor(
            7
        )
        == 7
    )

    assert (
        service.restore_sequence_floor(
            4
        )
        == 7
    )

    next_id = (
        service._next_intent_id(
            NOW
        )
    )

    assert (
        next_id.value
        == "ORD-20260810-000008"
    )


def test_sell_sequence_floor_is_monotonic() -> None:
    service = cast(
        Any,
        object.__new__(
            ExitExecutionService
        ),
    )

    service._sequence = 0
    service._sequence_lock = RLock()

    assert (
        service.restore_sequence_floor(
            11
        )
        == 11
    )

    assert (
        service.restore_sequence_floor(
            3
        )
        == 11
    )

    next_id = (
        service._next_intent_id(
            NOW
        )
    )

    assert (
        next_id.value
        == "EXIT-20260810-000012"
    )


@pytest.mark.parametrize(
    "value",
    [
        True,
        -1,
    ],
)
def test_sequence_floor_rejects_invalid_values(
    value,
) -> None:
    entry = cast(
        Any,
        object.__new__(
            ExecutionService
        ),
    )

    entry._sequence = 0
    entry._sequence_lock = RLock()

    if value is True:
        with pytest.raises(
            TypeError
        ):
            entry.restore_sequence_floor(
                value
            )
    else:
        with pytest.raises(
            ValueError
        ):
            entry.restore_sequence_floor(
                value
            )
