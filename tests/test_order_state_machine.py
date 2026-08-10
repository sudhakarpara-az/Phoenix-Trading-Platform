from datetime import date, datetime, timedelta

import pytest

from src.execution.execution_types import (
    ExecutionMode,
    OrderIntent,
    OrderIntentId,
    OrderType,
    TransactionType,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)
from src.strategy.strategy_types import EntryLevel


TRADING_DATE = date(2026, 8, 7)
EXPIRY = date(2026, 8, 11)
NOW = datetime(2026, 8, 7, 14, 30)


def make_intent() -> OrderIntent:
    signal = TradingSignal(
        signal_id=SignalId(
            "SIG-M06-T07"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        instrument_security_id="41009",
        instrument_symbol="NIFTY50-20260811-24450-CE",
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500,
        level_price=24500,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )

    option = SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol="NIFTY50-20260811-24450-CE",
                security_id="41009",
                option_type=OptionType.CALL,
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=205,
                bid=204.4,
                ask=204.9,
                volume=1000,
                open_interest=50000,
                received_at=NOW,
            ),
            greeks=OptionGreeks(
                delta=0.64,
                calculated_at=NOW,
            ),
        ),
        selected_at=NOW,
        selection_delta_target=0.64,
    )

    return OrderIntent(
        intent_id=OrderIntentId(
            "ORD-M06-T07"
        ),
        signal=signal,
        selected_option=option,
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=65,
        limit_price=206.0,
        execution_mode=ExecutionMode.DRY_RUN,
        created_at=NOW,
    )


def test_register_order() -> None:
    machine = OrderStateMachine()

    intent = make_intent()

    machine.register(
        intent
    )

    assert machine.count() == 1

    assert (
        machine.get_state(
            intent.intent_id
        )
        is OrderLifecycleState.CREATED
    )


def test_duplicate_registration_rejected() -> None:
    machine = OrderStateMachine()

    intent = make_intent()

    machine.register(intent)

    with pytest.raises(
        RuntimeError,
        match="order intent already registered",
    ):
        machine.register(intent)


def test_created_to_validated() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    transition = machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    assert (
        transition.from_state
        is OrderLifecycleState.CREATED
    )

    assert (
        transition.to_state
        is OrderLifecycleState.VALIDATED
    )


def test_validated_to_submitted() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    assert (
        machine.get_state(
            intent.intent_id
        )
        is OrderLifecycleState.SUBMITTED
    )


def test_submitted_to_pending() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.PENDING,
        NOW + timedelta(seconds=3),
    )

    assert (
        machine.get_state(
            intent.intent_id
        )
        is OrderLifecycleState.PENDING
    )


def test_pending_to_open() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.PENDING,
        NOW + timedelta(seconds=3),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.OPEN,
        NOW + timedelta(seconds=4),
    )

    assert (
        machine.get_state(
            intent.intent_id
        )
        is OrderLifecycleState.OPEN
    )


def test_open_to_partial_to_filled() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.OPEN,
        NOW + timedelta(seconds=3),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.PARTIALLY_FILLED,
        NOW + timedelta(seconds=4),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FILLED,
        NOW + timedelta(seconds=5),
    )

    assert (
        machine.get_state(
            intent.intent_id
        )
        is OrderLifecycleState.FILLED
    )

    assert machine.is_terminal(
        intent.intent_id
    ) is True


def test_submitted_can_fill_immediately() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FILLED,
        NOW + timedelta(seconds=3),
    )

    assert machine.is_terminal(
        intent.intent_id
    ) is True


def test_order_can_be_rejected() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.REJECTED,
        NOW + timedelta(seconds=1),
        message="eligibility rejected",
    )

    assert (
        machine.get_state(
            intent.intent_id
        )
        is OrderLifecycleState.REJECTED
    )


def test_open_order_can_be_cancelled() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.OPEN,
        NOW + timedelta(seconds=3),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.CANCELLED,
        NOW + timedelta(seconds=4),
    )

    assert machine.is_terminal(
        intent.intent_id
    ) is True


def test_terminal_state_cannot_transition() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FAILED,
        NOW + timedelta(seconds=1),
    )

    with pytest.raises(
        RuntimeError,
        match="invalid order state transition",
    ):
        machine.transition(
            intent.intent_id,
            OrderLifecycleState.SUBMITTED,
            NOW + timedelta(seconds=2),
        )


def test_same_state_transition_rejected() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    with pytest.raises(
        RuntimeError,
        match="order already in state CREATED",
    ):
        machine.transition(
            intent.intent_id,
            OrderLifecycleState.CREATED,
            NOW + timedelta(seconds=1),
        )


def test_history_is_preserved() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    history = machine.get_history(
        intent.intent_id
    )

    assert len(history) == 2

    assert (
        history[0].to_state
        is OrderLifecycleState.VALIDATED
    )

    assert (
        history[1].to_state
        is OrderLifecycleState.SUBMITTED
    )


def test_snapshot() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    snapshot = machine.snapshot(
        intent.intent_id
    )

    assert (
        snapshot.current_state
        is OrderLifecycleState.VALIDATED
    )

    assert snapshot.transition_count == 1


def test_unknown_order_raises() -> None:
    machine = OrderStateMachine()

    with pytest.raises(
        KeyError,
        match="order intent not registered",
    ):
        machine.get_state(
            OrderIntentId("UNKNOWN")
        )


def test_clear() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.clear()

    assert machine.count() == 0


def test_reconciliation_required_is_non_terminal() -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    machine.transition(
        intent.intent_id,
        (
            OrderLifecycleState
            .RECONCILIATION_REQUIRED
        ),
        NOW + timedelta(seconds=3),
    )

    assert (
        machine.get_state(
            intent.intent_id
        )
        is OrderLifecycleState
        .RECONCILIATION_REQUIRED
    )

    assert (
        machine.is_terminal(
            intent.intent_id
        )
        is False
    )


@pytest.mark.parametrize(
    "resolved_state",
    [
        OrderLifecycleState.PENDING,
        OrderLifecycleState.OPEN,
        OrderLifecycleState.PARTIALLY_FILLED,
        OrderLifecycleState.FILLED,
        OrderLifecycleState.REJECTED,
        OrderLifecycleState.CANCELLED,
        OrderLifecycleState.FAILED,
    ],
)
def test_reconciliation_required_can_resolve_to_broker_truth(
    resolved_state,
) -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    machine.transition(
        intent.intent_id,
        (
            OrderLifecycleState
            .RECONCILIATION_REQUIRED
        ),
        NOW + timedelta(seconds=3),
    )

    machine.transition(
        intent.intent_id,
        resolved_state,
        NOW + timedelta(seconds=4),
    )

    assert (
        machine.get_state(
            intent.intent_id
        )
        is resolved_state
    )



@pytest.mark.parametrize(
    "source_state",
    [
        OrderLifecycleState.PENDING,
        OrderLifecycleState.OPEN,
        OrderLifecycleState.PARTIALLY_FILLED,
    ],
)
def test_unresolved_submitted_order_can_require_reconciliation(
    source_state,
) -> None:
    machine = OrderStateMachine()
    intent = make_intent()

    machine.register(intent)

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.VALIDATED,
        NOW + timedelta(seconds=1),
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.SUBMITTED,
        NOW + timedelta(seconds=2),
    )

    if source_state is not OrderLifecycleState.PENDING:
        machine.transition(
            intent.intent_id,
            OrderLifecycleState.PENDING,
            NOW + timedelta(seconds=3),
        )

    if source_state is OrderLifecycleState.OPEN:
        machine.transition(
            intent.intent_id,
            OrderLifecycleState.OPEN,
            NOW + timedelta(seconds=4),
        )

    elif (
        source_state
        is OrderLifecycleState.PARTIALLY_FILLED
    ):
        machine.transition(
            intent.intent_id,
            OrderLifecycleState.PARTIALLY_FILLED,
            NOW + timedelta(seconds=4),
        )

    machine.transition(
        intent.intent_id,
        (
            OrderLifecycleState
            .RECONCILIATION_REQUIRED
        ),
        NOW + timedelta(seconds=5),
    )

    assert (
        machine.get_state(
            intent.intent_id
        )
        is OrderLifecycleState
        .RECONCILIATION_REQUIRED
    )

    assert (
        machine.is_terminal(
            intent.intent_id
        )
        is False
    )
