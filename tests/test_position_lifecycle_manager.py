from datetime import (
    date,
    datetime,
    timedelta,
)

import pytest

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
    RiskTriggerType,
    StopLossDefinition,
    StopLossState,
    TargetDefinition,
    TargetState,
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

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)

LATER = (
    NOW
    + timedelta(minutes=1)
)


def make_option() -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-24450-CE"
                ),
                security_id="41009",
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


def make_filled_position(
    *,
    quantity: int = 65,
    entry_price: float = 100,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T11"
        ),
        signal_id=SignalId(
            "SIG-M07-T11"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T11"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="DHAN-M07-T11",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )


def make_stop() -> StopLossDefinition:
    return StopLossDefinition(
        stop_price=85,
        risk_points=15,
        state=StopLossState.ARMED,
    )


def make_target() -> TargetDefinition:
    return TargetDefinition(
        executable_price=126,
        mapped_target_price=129,
        booking_zone_start=126,
        booking_zone_end=129,
        state=TargetState.ARMED,
    )


def make_managed_position(
    *,
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    entry_price: float = 100,
    realized_pnl: float = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
    with_stop: bool = True,
    with_target: bool = True,
) -> ManagedPosition:
    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-T11"
        ),
        position=make_filled_position(
            quantity=quantity,
            entry_price=entry_price,
        ),
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=realized_pnl,
        state=state,
        stop_loss=(
            make_stop()
            if with_stop
            else None
        ),
        target=(
            make_target()
            if with_target
            else None
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def make_components(
    position: ManagedPosition,
):
    registry = PositionRegistry()

    registry.register(
        position
    )

    manager = PositionLifecycleManager(
        registry=registry
    )

    return registry, manager


def test_target_exit_marks_position_pending() -> None:
    position = make_managed_position()

    registry, manager = make_components(
        position
    )

    result = manager.mark_exit_pending(
        position_id=position.position_id,
        trigger=RiskTriggerType.TARGET,
        changed_at=LATER,
    )

    assert (
        result.state
        is ManagedPositionState.EXIT_PENDING
    )

    assert result.target is not None

    assert (
        result.target.state
        is TargetState.TRIGGERED
    )

    assert (
        registry.require(
            position.position_id
        )
        is result
    )


def test_stop_exit_marks_position_pending() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    result = manager.mark_exit_pending(
        position_id=position.position_id,
        trigger=RiskTriggerType.STOP_LOSS,
        changed_at=LATER,
    )

    assert (
        result.state
        is ManagedPositionState.EXIT_PENDING
    )

    assert result.stop_loss is not None

    assert (
        result.stop_loss.state
        is StopLossState.TRIGGERED
    )


def test_force_exit_marks_position_pending() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    result = manager.mark_exit_pending(
        position_id=position.position_id,
        trigger=RiskTriggerType.FORCE_EXIT,
        changed_at=LATER,
    )

    assert (
        result.state
        is ManagedPositionState.EXIT_PENDING
    )

    assert result.stop_loss is not None
    assert result.target is not None

    assert (
        result.stop_loss.state
        is StopLossState.ARMED
    )

    assert (
        result.target.state
        is TargetState.ARMED
    )


def test_manual_exit_marks_position_pending() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    result = manager.mark_exit_pending(
        position_id=position.position_id,
        trigger=RiskTriggerType.MANUAL,
        changed_at=LATER,
    )

    assert (
        result.state
        is ManagedPositionState.EXIT_PENDING
    )


def test_none_trigger_cannot_mark_exit_pending() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit pending requires actionable trigger"
        ),
    ):
        manager.mark_exit_pending(
            position_id=position.position_id,
            trigger=RiskTriggerType.NONE,
            changed_at=LATER,
        )


def test_target_exit_requires_target() -> None:
    position = make_managed_position(
        with_target=False
    )

    _, manager = make_components(
        position
    )

    with pytest.raises(
        ValueError,
        match=(
            "TARGET exit requires configured target"
        ),
    ):
        manager.mark_exit_pending(
            position_id=position.position_id,
            trigger=RiskTriggerType.TARGET,
            changed_at=LATER,
        )


def test_stop_exit_requires_stop() -> None:
    position = make_managed_position(
        with_stop=False
    )

    _, manager = make_components(
        position
    )

    with pytest.raises(
        ValueError,
        match=(
            "STOP_LOSS exit requires configured stop loss"
        ),
    ):
        manager.mark_exit_pending(
            position_id=position.position_id,
            trigger=RiskTriggerType.STOP_LOSS,
            changed_at=LATER,
        )


def test_second_exit_pending_is_rejected() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    manager.mark_exit_pending(
        position_id=position.position_id,
        trigger=RiskTriggerType.TARGET,
        changed_at=LATER,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "position already has an exit pending"
        ),
    ):
        manager.mark_exit_pending(
            position_id=position.position_id,
            trigger=RiskTriggerType.STOP_LOSS,
            changed_at=(
                LATER
                + timedelta(seconds=1)
            ),
        )


def test_partial_exit_fill_updates_quantities() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    result = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=LATER,
    )

    assert result.open_quantity == 35
    assert result.closed_quantity == 30

    assert (
        result.state
        is ManagedPositionState.PARTIALLY_EXITED
    )


def test_partial_exit_updates_realized_profit() -> None:
    position = make_managed_position(
        entry_price=100
    )

    _, manager = make_components(
        position
    )

    result = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=LATER,
    )

    assert (
        result.realized_pnl
        == 780
    )


def test_partial_exit_updates_realized_loss() -> None:
    position = make_managed_position(
        entry_price=100
    )

    _, manager = make_components(
        position
    )

    result = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=85,
        filled_at=LATER,
    )

    assert (
        result.realized_pnl
        == -450
    )


def test_multiple_exit_fills_accumulate_realized_pnl() -> None:
    position = make_managed_position(
        entry_price=100
    )

    _, manager = make_components(
        position
    )

    first = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=20,
        fill_price=120,
        filled_at=LATER,
    )

    assert first.realized_pnl == 400
    assert first.open_quantity == 45

    second = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=10,
        fill_price=130,
        filled_at=(
            LATER
            + timedelta(seconds=1)
        ),
    )

    assert second.realized_pnl == 700
    assert second.closed_quantity == 30
    assert second.open_quantity == 35


def test_full_exit_closes_position() -> None:
    position = make_managed_position(
        entry_price=100
    )

    _, manager = make_components(
        position
    )

    result = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=65,
        fill_price=126,
        filled_at=LATER,
    )

    assert result.open_quantity == 0
    assert result.closed_quantity == 65

    assert (
        result.state
        is ManagedPositionState.CLOSED
    )

    assert (
        result.realized_pnl
        == 1690
    )


def test_partial_then_final_fill_closes_position() -> None:
    position = make_managed_position(
        entry_price=100
    )

    _, manager = make_components(
        position
    )

    manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=LATER,
    )

    result = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=35,
        fill_price=120,
        filled_at=(
            LATER
            + timedelta(seconds=1)
        ),
    )

    assert result.open_quantity == 0
    assert result.closed_quantity == 65

    assert (
        result.state
        is ManagedPositionState.CLOSED
    )

    # 30 * 26 = 780
    # 35 * 20 = 700
    # Total = 1480
    assert (
        result.realized_pnl
        == 1480
    )


def test_exit_fill_cannot_exceed_open_quantity() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit fill quantity cannot exceed "
            "open position quantity"
        ),
    ):
        manager.apply_exit_fill(
            position_id=position.position_id,
            fill_quantity=66,
            fill_price=126,
            filled_at=LATER,
        )


def test_zero_exit_fill_quantity_rejected() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit fill quantity must be greater than zero"
        ),
    ):
        manager.apply_exit_fill(
            position_id=position.position_id,
            fill_quantity=0,
            fill_price=126,
            filled_at=LATER,
        )


def test_zero_exit_fill_price_rejected() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit fill price must be greater than zero"
        ),
    ):
        manager.apply_exit_fill(
            position_id=position.position_id,
            fill_quantity=30,
            fill_price=0,
            filled_at=LATER,
        )


def test_closed_position_cannot_receive_another_fill() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=65,
        fill_price=126,
        filled_at=LATER,
    )

    with pytest.raises(
        ValueError,
        match=(
            "cannot apply exit fill to closed position"
        ),
    ):
        manager.apply_exit_fill(
            position_id=position.position_id,
            fill_quantity=1,
            fill_price=126,
            filled_at=(
                LATER
                + timedelta(seconds=1)
            ),
        )


def test_mark_reconciliation_required() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    result = (
        manager.mark_reconciliation_required(
            position_id=position.position_id,
            changed_at=LATER,
        )
    )

    assert (
        result.state
        is ManagedPositionState
        .RECONCILIATION_REQUIRED
    )


def test_reconciliation_required_blocks_new_exit_pending() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    manager.mark_reconciliation_required(
        position_id=position.position_id,
        changed_at=LATER,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "requires reconciliation before "
            "new exit can be marked pending"
        ),
    ):
        manager.mark_exit_pending(
            position_id=position.position_id,
            trigger=RiskTriggerType.FORCE_EXIT,
            changed_at=(
                LATER
                + timedelta(seconds=1)
            ),
        )


def test_restore_reconciled_full_open_position() -> None:
    position = make_managed_position(
        state=ManagedPositionState.EXIT_PENDING
    )

    _, manager = make_components(
        position
    )

    result = (
        manager.restore_after_reconciliation(
            position_id=position.position_id,
            changed_at=LATER,
        )
    )

    assert (
        result.state
        is ManagedPositionState.OPEN
    )

    assert result.open_quantity == 65
    assert result.closed_quantity == 0


def test_restore_reconciled_partial_position() -> None:
    position = make_managed_position(
        open_quantity=35,
        closed_quantity=30,
        realized_pnl=780,
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        ),
    )

    _, manager = make_components(
        position
    )

    result = (
        manager.restore_after_reconciliation(
            position_id=position.position_id,
            changed_at=LATER,
        )
    )

    assert (
        result.state
        is ManagedPositionState
        .PARTIALLY_EXITED
    )

    assert result.open_quantity == 35
    assert result.closed_quantity == 30
    assert result.realized_pnl == 780


def test_restore_requires_reconciliation_state() -> None:
    position = make_managed_position()

    _, manager = make_components(
        position
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "position is not awaiting "
            "exit reconciliation"
        ),
    ):
        manager.restore_after_reconciliation(
            position_id=position.position_id,
            changed_at=LATER,
        )


def test_mark_exit_pending_preserves_quantity() -> None:
    position = make_managed_position(
        open_quantity=35,
        closed_quantity=30,
        realized_pnl=780,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    _, manager = make_components(
        position
    )

    result = manager.mark_exit_pending(
        position_id=position.position_id,
        trigger=RiskTriggerType.STOP_LOSS,
        changed_at=LATER,
    )

    assert result.open_quantity == 35
    assert result.closed_quantity == 30
    assert result.realized_pnl == 780

    assert (
        result.state
        is ManagedPositionState.EXIT_PENDING
    )


def test_fill_uses_actual_m06_entry_price() -> None:
    position = make_managed_position(
        entry_price=100.65
    )

    _, manager = make_components(
        position
    )

    result = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126.65,
        filled_at=LATER,
    )

    # 26 points × 30
    assert (
        result.realized_pnl
        == pytest.approx(780)
    )


def test_registry_contains_latest_snapshot() -> None:
    position = make_managed_position()

    registry, manager = make_components(
        position
    )

    updated = manager.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=126,
        filled_at=LATER,
    )

    stored = registry.require(
        position.position_id
    )

    assert stored is updated
    assert stored.open_quantity == 35