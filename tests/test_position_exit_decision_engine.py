from datetime import date, datetime

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
from src.risk.position_exit_decision_engine import (
    PositionExitDecisionEngine,
    PositionExitDecisionStatus,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    RiskTriggerType,
)
from src.risk.stop_loss_trigger_monitor import (
    StopLossTriggerResult,
    StopLossTriggerStatus,
)
from src.risk.target_trigger_monitor import (
    TargetTriggerResult,
    TargetTriggerStatus,
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
    position_id: str = "POS-T10",
    quantity: int = 65,
) -> FilledPosition:
    return FilledPosition(
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
                order_id=f"DHAN-{position_id}",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=100,
        filled_at=NOW,
    )


def make_position(
    *,
    position_id: str = "POS-T10",
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    return ManagedPosition(
        risk_id=PositionRiskId(
            f"RISK-{position_id}"
        ),
        position=make_filled_position(
            position_id=position_id,
            quantity=quantity,
        ),
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
        stop_loss=None,
        target=None,
        created_at=NOW,
        updated_at=NOW,
    )


def make_target_result(
    *,
    position_id: str = "POS-T10",
    triggered: bool = True,
) -> TargetTriggerResult:
    return TargetTriggerResult(
        status=(
            TargetTriggerStatus.TRIGGERED
            if triggered
            else TargetTriggerStatus.NOT_TRIGGERED
        ),
        position_id=FilledPositionId(
            position_id
        ),
        trigger=(
            RiskTriggerType.TARGET
            if triggered
            else RiskTriggerType.NONE
        ),
        current_ltp=126,
        executable_target_price=126,
        mapped_target_price=129,
        booking_zone_start=126,
        booking_zone_end=129,
        price_received_at=NOW,
        evaluated_at=NOW,
    )


def make_stop_result(
    *,
    position_id: str = "POS-T10",
    triggered: bool = True,
) -> StopLossTriggerResult:
    return StopLossTriggerResult(
        status=(
            StopLossTriggerStatus.TRIGGERED
            if triggered
            else StopLossTriggerStatus.NOT_TRIGGERED
        ),
        position_id=FilledPositionId(
            position_id
        ),
        trigger=(
            RiskTriggerType.STOP_LOSS
            if triggered
            else RiskTriggerType.NONE
        ),
        current_ltp=85,
        stop_price=85,
        risk_points=15,
        price_received_at=NOW,
        evaluated_at=NOW,
    )


def test_no_trigger_means_no_exit() -> None:
    engine = PositionExitDecisionEngine()

    position = make_position()

    result = engine.decide(
        position=position,
        target_result=(
            make_target_result(
                triggered=False
            )
        ),
        stop_result=(
            make_stop_result(
                triggered=False
            )
        ),
        force_exit=False,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus.NO_EXIT
    )

    assert (
        result.trigger
        is RiskTriggerType.NONE
    )

    assert result.exit_required is False

    assert result.quantity == 65


def test_target_trigger_requires_exit() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=make_target_result(),
        stop_result=(
            make_stop_result(
                triggered=False
            )
        ),
        force_exit=False,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .EXIT_REQUIRED
    )

    assert (
        result.trigger
        is RiskTriggerType.TARGET
    )

    assert result.exit_required is True

    assert result.quantity == 65


def test_stop_trigger_requires_exit() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=(
            make_target_result(
                triggered=False
            )
        ),
        stop_result=make_stop_result(),
        force_exit=False,
        decided_at=NOW,
    )

    assert result.exit_required is True

    assert (
        result.trigger
        is RiskTriggerType.STOP_LOSS
    )


def test_force_exit_requires_exit() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=NOW,
    )

    assert result.exit_required is True

    assert (
        result.trigger
        is RiskTriggerType.FORCE_EXIT
    )


def test_force_exit_has_priority_over_stop() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=None,
        stop_result=make_stop_result(),
        force_exit=True,
        decided_at=NOW,
    )

    assert (
        result.trigger
        is RiskTriggerType.FORCE_EXIT
    )


def test_force_exit_has_priority_over_target() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=make_target_result(),
        stop_result=None,
        force_exit=True,
        decided_at=NOW,
    )

    assert (
        result.trigger
        is RiskTriggerType.FORCE_EXIT
    )


def test_force_exit_has_priority_when_both_price_triggers_fire() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=make_target_result(),
        stop_result=make_stop_result(),
        force_exit=True,
        decided_at=NOW,
    )

    assert (
        result.trigger
        is RiskTriggerType.FORCE_EXIT
    )


def test_stop_has_priority_over_target() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=make_target_result(),
        stop_result=make_stop_result(),
        force_exit=False,
        decided_at=NOW,
    )

    assert (
        result.trigger
        is RiskTriggerType.STOP_LOSS
    )


def test_partial_position_exits_only_open_quantity() -> None:
    engine = PositionExitDecisionEngine()

    position = make_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=make_stop_result(),
        force_exit=False,
        decided_at=NOW,
    )

    assert result.exit_required is True
    assert result.quantity == 35


def test_force_exit_partial_position_uses_remaining_quantity() -> None:
    engine = PositionExitDecisionEngine()

    position = make_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=NOW,
    )

    assert result.exit_required is True
    assert result.quantity == 35

    assert (
        result.trigger
        is RiskTriggerType.FORCE_EXIT
    )


def test_closed_position_never_requires_exit() -> None:
    engine = PositionExitDecisionEngine()

    position = make_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    result = engine.decide(
        position=position,
        target_result=make_target_result(),
        stop_result=make_stop_result(),
        force_exit=True,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .POSITION_CLOSED
    )

    assert result.exit_required is False
    assert result.quantity == 0

    assert (
        result.trigger
        is RiskTriggerType.NONE
    )


def test_exit_pending_blocks_new_target_exit() -> None:
    engine = PositionExitDecisionEngine()

    position = make_position(
        state=ManagedPositionState.EXIT_PENDING,
    )

    result = engine.decide(
        position=position,
        target_result=make_target_result(),
        stop_result=None,
        force_exit=False,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .EXIT_ALREADY_PENDING
    )

    assert result.exit_required is False


def test_exit_pending_blocks_new_stop_exit() -> None:
    engine = PositionExitDecisionEngine()

    position = make_position(
        state=ManagedPositionState.EXIT_PENDING,
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=make_stop_result(),
        force_exit=False,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .EXIT_ALREADY_PENDING
    )


def test_exit_pending_blocks_force_exit_directly() -> None:
    """
    An existing SELL must be reconciled by M06-T20 before a
    replacement force-exit order can be generated.
    """

    engine = PositionExitDecisionEngine()

    position = make_position(
        state=ManagedPositionState.EXIT_PENDING,
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .EXIT_ALREADY_PENDING
    )

    assert result.exit_required is False


def test_reconciliation_required_blocks_direct_exit() -> None:
    engine = PositionExitDecisionEngine()

    position = make_position(
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        ),
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus
        .RECONCILIATION_REQUIRED
    )

    assert result.exit_required is False


def test_target_result_for_wrong_position_rejected() -> None:
    engine = PositionExitDecisionEngine()

    with pytest.raises(
        ValueError,
        match=(
            "target trigger result does not belong "
            "to managed position"
        ),
    ):
        engine.decide(
            position=make_position(
                position_id="POS-001"
            ),
            target_result=make_target_result(
                position_id="POS-OTHER"
            ),
            stop_result=None,
            force_exit=False,
            decided_at=NOW,
        )


def test_stop_result_for_wrong_position_rejected() -> None:
    engine = PositionExitDecisionEngine()

    with pytest.raises(
        ValueError,
        match=(
            "stop-loss trigger result does not belong "
            "to managed position"
        ),
    ):
        engine.decide(
            position=make_position(
                position_id="POS-001"
            ),
            target_result=None,
            stop_result=make_stop_result(
                position_id="POS-OTHER"
            ),
            force_exit=False,
            decided_at=NOW,
        )


def test_wrong_non_triggered_target_result_does_not_matter() -> None:
    """
    Only actionable trigger results need strict identity
    validation.
    """

    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(
            position_id="POS-001"
        ),
        target_result=make_target_result(
            position_id="POS-OTHER",
            triggered=False,
        ),
        stop_result=None,
        force_exit=False,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus.NO_EXIT
    )


def test_no_monitor_results_is_valid() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=None,
        stop_result=None,
        force_exit=False,
        decided_at=NOW,
    )

    assert (
        result.status
        is PositionExitDecisionStatus.NO_EXIT
    )


def test_decision_preserves_position_id() -> None:
    engine = PositionExitDecisionEngine()

    position = make_position(
        position_id="POS-SPECIAL"
    )

    result = engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=NOW,
    )

    assert (
        result.position_id
        == position.position_id
    )


def test_decision_timestamp_preserved() -> None:
    engine = PositionExitDecisionEngine()

    result = engine.decide(
        position=make_position(),
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=NOW,
    )

    assert result.decided_at == NOW