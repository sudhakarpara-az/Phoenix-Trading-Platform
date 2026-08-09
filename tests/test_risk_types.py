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
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionPnL,
    PositionRiskId,
    PositionRiskSnapshot,
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
                strike=24450.0,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=100.0,
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
    entry_price: float = 100.65,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T01"
        ),
        signal_id=SignalId(
            "SIG-M07-T01"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T01"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="DHAN-M07-T01",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )


def make_stop_loss() -> StopLossDefinition:
    return StopLossDefinition(
        stop_price=85.65,
        risk_points=15.0,
    )


def make_target() -> TargetDefinition:
    return TargetDefinition(
        executable_price=126.0,
        mapped_target_price=129.0,
        booking_zone_start=126.0,
        booking_zone_end=129.0,
    )


def make_pnl() -> PositionPnL:
    return PositionPnL(
        realized_pnl=0.0,
        unrealized_pnl=780.0,
        total_pnl=780.0,
        unrealized_points=12.0,
        calculated_at=NOW,
    )


def test_position_risk_id() -> None:
    risk_id = PositionRiskId(
        "RISK-001"
    )

    assert risk_id.value == "RISK-001"


def test_empty_position_risk_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="position risk id cannot be empty",
    ):
        PositionRiskId(" ")


def test_stop_loss_definition() -> None:
    stop = make_stop_loss()

    assert stop.stop_price == 85.65
    assert stop.risk_points == 15.0

    assert (
        stop.state
        is StopLossState.ARMED
    )


def test_stop_loss_price_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "stop_price must be greater than zero"
        ),
    ):
        StopLossDefinition(
            stop_price=0,
            risk_points=15,
        )


def test_stop_loss_risk_points_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "risk_points must be greater than zero"
        ),
    ):
        StopLossDefinition(
            stop_price=85,
            risk_points=0,
        )


def test_configured_stop_cannot_be_not_configured() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "configured stop loss cannot have "
            "NOT_CONFIGURED state"
        ),
    ):
        StopLossDefinition(
            stop_price=85,
            risk_points=15,
            state=StopLossState.NOT_CONFIGURED,
        )


def test_target_definition() -> None:
    target = make_target()

    assert (
        target.executable_price
        == 126
    )

    assert (
        target.mapped_target_price
        == 129
    )

    assert (
        target.state
        is TargetState.ARMED
    )


def test_target_booking_zone_order() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "booking_zone_start cannot exceed "
            "booking_zone_end"
        ),
    ):
        TargetDefinition(
            executable_price=126,
            mapped_target_price=129,
            booking_zone_start=129,
            booking_zone_end=126,
        )


def test_target_executable_price_must_be_in_zone() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "executable_price must be inside "
            "booking zone"
        ),
    ):
        TargetDefinition(
            executable_price=125,
            mapped_target_price=129,
            booking_zone_start=126,
            booking_zone_end=129,
        )


def test_target_mapped_price_cannot_be_below_execution() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "mapped_target_price cannot be below "
            "executable_price"
        ),
    ):
        TargetDefinition(
            executable_price=130,
            mapped_target_price=129,
            booking_zone_start=130,
            booking_zone_end=130,
        )


def test_pnl_creation() -> None:
    pnl = make_pnl()

    assert pnl.realized_pnl == 0
    assert pnl.unrealized_pnl == 780
    assert pnl.total_pnl == 780
    assert pnl.unrealized_points == 12


def test_pnl_total_must_match_components() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "total_pnl must equal realized_pnl "
            r"\+ unrealized_pnl"
        ),
    ):
        PositionPnL(
            realized_pnl=100,
            unrealized_pnl=200,
            total_pnl=500,
            unrealized_points=5,
            calculated_at=NOW,
        )


def test_risk_snapshot_full_open_position() -> None:
    snapshot = PositionRiskSnapshot(
        current_ltp=112.65,
        open_quantity=65,
        original_quantity=65,
        closed_quantity=0,
        stop_loss=make_stop_loss(),
        target=make_target(),
        pnl=make_pnl(),
        trigger=RiskTriggerType.NONE,
        captured_at=NOW,
    )

    assert snapshot.open_quantity == 65
    assert snapshot.closed_quantity == 0


def test_risk_snapshot_partial_position() -> None:
    pnl = PositionPnL(
        realized_pnl=780,
        unrealized_pnl=420,
        total_pnl=1200,
        unrealized_points=12,
        calculated_at=NOW,
    )

    snapshot = PositionRiskSnapshot(
        current_ltp=112.65,
        open_quantity=35,
        original_quantity=65,
        closed_quantity=30,
        stop_loss=make_stop_loss(),
        target=make_target(),
        pnl=pnl,
        trigger=RiskTriggerType.NONE,
        captured_at=NOW,
    )

    assert snapshot.open_quantity == 35
    assert snapshot.closed_quantity == 30


def test_snapshot_quantities_must_balance() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "open_quantity \\+ closed_quantity "
            "must equal original_quantity"
        ),
    ):
        PositionRiskSnapshot(
            current_ltp=112,
            open_quantity=35,
            original_quantity=65,
            closed_quantity=20,
            stop_loss=None,
            target=None,
            pnl=make_pnl(),
            trigger=RiskTriggerType.NONE,
            captured_at=NOW,
        )


def test_stop_trigger_requires_stop_definition() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "STOP_LOSS trigger requires stop_loss"
        ),
    ):
        PositionRiskSnapshot(
            current_ltp=85,
            open_quantity=65,
            original_quantity=65,
            closed_quantity=0,
            stop_loss=None,
            target=make_target(),
            pnl=make_pnl(),
            trigger=RiskTriggerType.STOP_LOSS,
            captured_at=NOW,
        )


def test_target_trigger_requires_target_definition() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "TARGET trigger requires target"
        ),
    ):
        PositionRiskSnapshot(
            current_ltp=126,
            open_quantity=65,
            original_quantity=65,
            closed_quantity=0,
            stop_loss=make_stop_loss(),
            target=None,
            pnl=make_pnl(),
            trigger=RiskTriggerType.TARGET,
            captured_at=NOW,
        )


def test_managed_open_position() -> None:
    position = make_filled_position()

    managed = ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-001"
        ),
        position=position,
        open_quantity=65,
        closed_quantity=0,
        realized_pnl=0,
        state=ManagedPositionState.OPEN,
        stop_loss=make_stop_loss(),
        target=make_target(),
        created_at=NOW,
        updated_at=NOW,
    )

    assert managed.position_id == position.position_id

    assert (
        managed.entry_price
        == 100.65
    )

    assert (
        managed.original_quantity
        == 65
    )

    assert managed.is_open is True


def test_managed_position_uses_actual_m06_fill() -> None:
    position = make_filled_position(
        entry_price=100.65
    )

    managed = ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-001"
        ),
        position=position,
        open_quantity=65,
        closed_quantity=0,
        realized_pnl=0,
        state=ManagedPositionState.OPEN,
        stop_loss=None,
        target=None,
        created_at=NOW,
        updated_at=NOW,
    )

    assert (
        managed.entry_price
        == position.entry_price
        == 100.65
    )


def test_managed_quantities_must_equal_position_quantity() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "managed quantities must equal "
            "filled position quantity"
        ),
    ):
        ManagedPosition(
            risk_id=PositionRiskId(
                "RISK-M07-001"
            ),
            position=make_filled_position(),
            open_quantity=30,
            closed_quantity=20,
            realized_pnl=0,
            state=ManagedPositionState.OPEN,
            stop_loss=None,
            target=None,
            created_at=NOW,
            updated_at=NOW,
        )


def test_closed_position_requires_zero_open_quantity() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "CLOSED position must have zero "
            "open quantity"
        ),
    ):
        ManagedPosition(
            risk_id=PositionRiskId(
                "RISK-M07-001"
            ),
            position=make_filled_position(),
            open_quantity=65,
            closed_quantity=0,
            realized_pnl=0,
            state=ManagedPositionState.CLOSED,
            stop_loss=None,
            target=None,
            created_at=NOW,
            updated_at=NOW,
        )


def test_closed_position_is_valid() -> None:
    managed = ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-001"
        ),
        position=make_filled_position(),
        open_quantity=0,
        closed_quantity=65,
        realized_pnl=1500,
        state=ManagedPositionState.CLOSED,
        stop_loss=None,
        target=None,
        created_at=NOW,
        updated_at=NOW,
    )

    assert managed.is_open is False

    assert (
        managed.state
        is ManagedPositionState.CLOSED
    )


def test_partial_position_state() -> None:
    managed = ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-001"
        ),
        position=make_filled_position(),
        open_quantity=35,
        closed_quantity=30,
        realized_pnl=780,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
        stop_loss=make_stop_loss(),
        target=make_target(),
        created_at=NOW,
        updated_at=NOW,
    )

    assert managed.open_quantity == 35
    assert managed.closed_quantity == 30
    assert managed.is_open is True


def test_partial_position_requires_closed_quantity() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "PARTIALLY_EXITED position requires "
            "both open and closed quantity"
        ),
    ):
        ManagedPosition(
            risk_id=PositionRiskId(
                "RISK-M07-001"
            ),
            position=make_filled_position(),
            open_quantity=65,
            closed_quantity=0,
            realized_pnl=0,
            state=(
                ManagedPositionState
                .PARTIALLY_EXITED
            ),
            stop_loss=None,
            target=None,
            created_at=NOW,
            updated_at=NOW,
        )


def test_updated_time_cannot_precede_creation() -> None:
    earlier = datetime(
        2026,
        8,
        7,
        14,
        29,
    )

    with pytest.raises(
        ValueError,
        match=(
            "updated_at cannot be before created_at"
        ),
    ):
        ManagedPosition(
            risk_id=PositionRiskId(
                "RISK-M07-001"
            ),
            position=make_filled_position(),
            open_quantity=65,
            closed_quantity=0,
            realized_pnl=0,
            state=ManagedPositionState.OPEN,
            stop_loss=None,
            target=None,
            created_at=NOW,
            updated_at=earlier,
        )