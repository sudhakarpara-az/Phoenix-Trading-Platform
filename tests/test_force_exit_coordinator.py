from datetime import (
    date,
    datetime,
    time,
)

from src.execution.execution_types import (
    BrokerOrderReference,
    OrderIntentId,
)
from src.execution.position_exit_types import (
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
from src.risk.force_exit_coordinator import (
    ForceExitAction,
    ForceExitCoordinator,
    ForceExitReason,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    RiskTriggerType,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


EXPIRY = date(
    2026,
    8,
    11,
)

BEFORE = datetime(
    2026,
    8,
    7,
    15,
    14,
    59,
)

FORCE_TIME = datetime(
    2026,
    8,
    7,
    15,
    15,
)

AFTER = datetime(
    2026,
    8,
    7,
    15,
    16,
)


def make_option(
    *,
    security_id: str = "41009",
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    f"NIFTY-{security_id}-CE"
                ),
                security_id=security_id,
                option_type=OptionType.CALL,
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
                received_at=BEFORE,
            ),
            greeks=OptionGreeks(
                delta=0.64,
                calculated_at=BEFORE,
            ),
        ),
        selected_at=BEFORE,
        selection_delta_target=0.64,
    )


def make_position(
    *,
    position_id: str = "POS-T14",
    risk_id: str = "RISK-T14",
    security_id: str = "41009",
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    filled = FilledPosition(
        position_id=FilledPositionId(
            position_id
        ),
        signal_id=SignalId(
            f"SIG-{position_id}"
        ),
        entry_intent_id=OrderIntentId(
            f"ORD-{position_id}"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id=(
                    f"DHAN-{position_id}"
                ),
            )
        ),
        selected_option=make_option(
            security_id=security_id
        ),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=100,
        filled_at=BEFORE,
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            risk_id
        ),
        position=filled,
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
        stop_loss=None,
        target=None,
        created_at=BEFORE,
        updated_at=BEFORE,
    )


def make_registry(
    *positions: ManagedPosition,
) -> PositionRegistry:
    registry = PositionRegistry()

    for position in positions:
        registry.register(
            position
        )

    return registry


def test_default_force_exit_time_is_1515() -> None:
    coordinator = ForceExitCoordinator(
        registry=make_registry()
    )

    assert (
        coordinator.force_exit_time
        == time(15, 15)
    )


def test_before_1515_force_exit_not_reached() -> None:
    coordinator = ForceExitCoordinator(
        registry=make_registry()
    )

    assert coordinator.is_force_exit_time(
        BEFORE
    ) is False


def test_exactly_1515_force_exit_is_reached() -> None:
    coordinator = ForceExitCoordinator(
        registry=make_registry()
    )

    assert coordinator.is_force_exit_time(
        FORCE_TIME
    ) is True


def test_after_1515_force_exit_is_reached() -> None:
    coordinator = ForceExitCoordinator(
        registry=make_registry()
    )

    assert coordinator.is_force_exit_time(
        AFTER
    ) is True


def test_open_position_before_1515_has_no_action() -> None:
    position = make_position()

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=BEFORE,
    )

    assert (
        result.action
        is ForceExitAction.NONE
    )

    assert (
        result.reason
        is ForceExitReason
        .BEFORE_FORCE_EXIT_TIME
    )

    assert result.force_exit_required is False


def test_open_position_at_1515_requires_force_exit() -> None:
    position = make_position()

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is ForceExitAction.NEW_FORCE_EXIT
    )

    assert (
        result.reason
        is ForceExitReason.OPEN_POSITION
    )

    assert (
        result.trigger
        is RiskTriggerType.FORCE_EXIT
    )

    assert result.quantity == 65
    assert result.force_exit_required is True


def test_open_position_after_1515_requires_force_exit() -> None:
    position = make_position()

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=AFTER,
    )

    assert result.force_exit_required is True
    assert result.quantity == 65


def test_partial_position_force_exits_remaining_quantity_only() -> None:
    position = make_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is ForceExitAction.NEW_FORCE_EXIT
    )

    assert (
        result.reason
        is ForceExitReason.PARTIAL_POSITION
    )

    assert result.quantity == 35
    assert result.force_exit_required is True


def test_closed_position_has_no_force_exit() -> None:
    position = make_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is ForceExitAction.NONE
    )

    assert (
        result.reason
        is ForceExitReason.POSITION_CLOSED
    )

    assert result.quantity == 0

    assert (
        result.trigger
        is RiskTriggerType.NONE
    )


def test_exit_pending_at_1515_requires_reconciliation() -> None:
    position = make_position(
        state=ManagedPositionState.EXIT_PENDING,
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert (
        result.reason
        is ForceExitReason
        .EXIT_ALREADY_PENDING
    )

    assert (
        result.reconciliation_required
        is True
    )

    assert result.force_exit_required is False

    assert result.quantity == 65


def test_exit_pending_does_not_request_second_sell() -> None:
    position = make_position(
        state=ManagedPositionState.EXIT_PENDING,
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is not ForceExitAction.NEW_FORCE_EXIT
    )


def test_reconciliation_required_stays_on_reconciliation_path() -> None:
    position = make_position(
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        ),
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert (
        result.reason
        is ForceExitReason
        .RECONCILIATION_ALREADY_REQUIRED
    )

    assert (
        result.reconciliation_required
        is True
    )


def test_reconciliation_partial_position_uses_open_quantity() -> None:
    position = make_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        ),
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.reconciliation_required
        is True
    )

    assert result.quantity == 35


def test_empty_registry_produces_empty_batch() -> None:
    coordinator = ForceExitCoordinator(
        registry=make_registry()
    )

    batch = coordinator.evaluate_all(
        evaluated_at=FORCE_TIME
    )

    assert (
        batch.force_exit_time_reached
        is True
    )

    assert batch.instructions == ()
    assert batch.new_force_exits == ()
    assert batch.reconciliations == ()


def test_batch_before_1515_has_no_force_exits() -> None:
    position = make_position()

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    batch = coordinator.evaluate_all(
        evaluated_at=BEFORE
    )

    assert (
        batch.force_exit_time_reached
        is False
    )

    assert batch.new_force_exits == ()
    assert batch.reconciliations == ()


def test_batch_contains_new_force_exit() -> None:
    position = make_position()

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    batch = coordinator.evaluate_all(
        evaluated_at=FORCE_TIME
    )

    assert len(
        batch.instructions
    ) == 1

    assert len(
        batch.new_force_exits
    ) == 1

    assert (
        batch.new_force_exits[0]
        .position_id
        == position.position_id
    )


def test_batch_contains_reconciliation_instruction() -> None:
    position = make_position(
        state=ManagedPositionState.EXIT_PENDING
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    batch = coordinator.evaluate_all(
        evaluated_at=FORCE_TIME
    )

    assert len(
        batch.reconciliations
    ) == 1

    assert (
        batch.new_force_exits
        == ()
    )


def test_batch_separates_open_and_pending_positions() -> None:
    open_position = make_position(
        position_id="POS-OPEN",
        risk_id="RISK-OPEN",
        security_id="41009",
    )

    pending_position = make_position(
        position_id="POS-PENDING",
        risk_id="RISK-PENDING",
        security_id="41019",
        state=ManagedPositionState.EXIT_PENDING,
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            open_position,
            pending_position,
        )
    )

    batch = coordinator.evaluate_all(
        evaluated_at=FORCE_TIME
    )

    assert len(
        batch.instructions
    ) == 2

    assert len(
        batch.new_force_exits
    ) == 1

    assert len(
        batch.reconciliations
    ) == 1

    assert (
        batch.new_force_exits[0]
        .position_id
        == open_position.position_id
    )

    assert (
        batch.reconciliations[0]
        .position_id
        == pending_position.position_id
    )


def test_closed_position_not_in_actionable_batch_views() -> None:
    closed = make_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            closed
        )
    )

    batch = coordinator.evaluate_all(
        evaluated_at=FORCE_TIME
    )

    assert len(
        batch.instructions
    ) == 1

    assert batch.new_force_exits == ()
    assert batch.reconciliations == ()


def test_custom_force_exit_time_supported() -> None:
    position = make_position()

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        ),
        force_exit_time=time(
            15,
            10,
        ),
    )

    evaluated_at = datetime(
        2026,
        8,
        7,
        15,
        10,
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=evaluated_at,
    )

    assert result.force_exit_required is True


def test_instruction_preserves_evaluation_time() -> None:
    position = make_position()

    coordinator = ForceExitCoordinator(
        registry=make_registry(
            position
        )
    )

    result = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        result.evaluated_at
        == FORCE_TIME
    )


def test_batch_preserves_evaluation_time() -> None:
    coordinator = ForceExitCoordinator(
        registry=make_registry()
    )

    batch = coordinator.evaluate_all(
        evaluated_at=FORCE_TIME
    )

    assert (
        batch.evaluated_at
        == FORCE_TIME
    )