from datetime import date, datetime

import math
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
from src.risk.position_pnl_calculator import (
    ExitFill,
)
from src.risk.position_risk_snapshot_service import (
    PositionRiskSnapshotService,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    RiskTriggerType,
    StopLossDefinition,
    TargetDefinition,
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
    entry_price: float = 100.0,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T05"
        ),
        signal_id=SignalId(
            "SIG-M07-T05"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T05"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="DHAN-M07-T05",
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
        stop_price=85.0,
        risk_points=15.0,
    )


def make_target() -> TargetDefinition:
    return TargetDefinition(
        executable_price=126.0,
        mapped_target_price=129.0,
        booking_zone_start=126.0,
        booking_zone_end=129.0,
    )


def make_managed_position(
    *,
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    entry_price: float = 100.0,
    realized_pnl: float = 0.0,
    with_stop: bool = True,
    with_target: bool = True,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-T05"
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


def test_full_open_position_snapshot() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=112.0,
        captured_at=NOW,
    )

    snapshot = result.snapshot

    assert snapshot.current_ltp == 112.0
    assert snapshot.open_quantity == 65
    assert snapshot.closed_quantity == 0
    assert snapshot.original_quantity == 65

    assert (
        snapshot.trigger
        is RiskTriggerType.NONE
    )


def test_unrealized_profit_flows_into_snapshot() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position(
                entry_price=100
            )
        ),
        current_ltp=112,
        captured_at=NOW,
    )

    assert (
        result.snapshot.pnl
        .unrealized_points
        == 12
    )

    assert (
        result.snapshot.pnl
        .unrealized_pnl
        == 780
    )

    assert (
        result.snapshot.pnl
        .total_pnl
        == 780
    )


def test_unrealized_loss_flows_into_snapshot() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position(
                entry_price=100
            )
        ),
        current_ltp=90,
        captured_at=NOW,
    )

    assert (
        result.snapshot.pnl
        .unrealized_points
        == -10
    )

    assert (
        result.snapshot.pnl
        .unrealized_pnl
        == -650
    )


def test_stop_distance() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=100,
        captured_at=NOW,
    )

    # Current 100
    # SL 85
    assert (
        result.stop_distance_points
        == 15
    )


def test_stop_distance_becomes_zero_at_stop() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=85,
        captured_at=NOW,
    )

    assert (
        result.stop_distance_points
        == 0
    )


def test_stop_distance_can_be_negative_after_cross() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=84,
        captured_at=NOW,
    )

    assert (
        result.stop_distance_points
        == -1
    )


def test_target_distance() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=112,
        captured_at=NOW,
    )

    # Target trigger = 126
    assert (
        result.target_distance_points
        == 14
    )


def test_target_distance_zero_at_target() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=126,
        captured_at=NOW,
    )

    assert (
        result.target_distance_points
        == 0
    )


def test_target_distance_negative_above_target() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=130,
        captured_at=NOW,
    )

    assert (
        result.target_distance_points
        == -4
    )


def test_open_risk_amount() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=100,
        captured_at=NOW,
    )

    # Current premium risk to SL:
    # 100 - 85 = 15
    #
    # Qty = 65
    #
    # 15 * 65 = 975

    assert (
        result.open_risk_points
        == 15
    )

    assert (
        result.open_risk_amount
        == 975
    )


def test_entry_risk_amount() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=110,
        captured_at=NOW,
    )

    # Configured entry risk:
    # 15 points * 65
    assert (
        result.entry_risk_amount
        == 975
    )


def test_open_risk_amount_increases_as_profit_grows() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=120,
        captured_at=NOW,
    )

    # Distance from current price to unchanged SL:
    # 120 - 85 = 35

    assert (
        result.open_risk_points
        == 35
    )

    assert (
        result.open_risk_amount
        == 2275
    )


def test_open_risk_is_zero_after_stop_cross() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=84,
        captured_at=NOW,
    )

    assert (
        result.open_risk_points
        == 0
    )

    assert (
        result.open_risk_amount
        == 0
    )


def test_no_stop_has_no_stop_risk_metrics() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position(
                with_stop=False
            )
        ),
        current_ltp=100,
        captured_at=NOW,
    )

    assert (
        result.stop_distance_points
        is None
    )

    assert (
        result.open_risk_points
        is None
    )

    assert (
        result.open_risk_amount
        is None
    )

    assert (
        result.entry_risk_amount
        is None
    )


def test_no_target_has_no_target_distance() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position(
                with_target=False
            )
        ),
        current_ltp=100,
        captured_at=NOW,
    )

    assert (
        result.target_distance_points
        is None
    )


def test_partial_position_snapshot() -> None:
    service = PositionRiskSnapshotService()

    managed = make_managed_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        entry_price=100,
        realized_pnl=780,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    result = service.build(
        managed_position=managed,
        current_ltp=112,
        exit_fills=(
            ExitFill(
                quantity=30,
                price=126,
                filled_at=NOW,
            ),
        ),
        captured_at=NOW,
    )

    assert (
        result.snapshot.open_quantity
        == 35
    )

    assert (
        result.snapshot.closed_quantity
        == 30
    )

    assert (
        result.snapshot.pnl.realized_pnl
        == 780
    )

    assert (
        result.snapshot.pnl.unrealized_pnl
        == 420
    )

    assert (
        result.snapshot.pnl.total_pnl
        == 1200
    )


def test_partial_position_risk_uses_remaining_quantity() -> None:
    service = PositionRiskSnapshotService()

    managed = make_managed_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    result = service.build(
        managed_position=managed,
        current_ltp=100,
        exit_fills=(
            ExitFill(
                quantity=30,
                price=126,
                filled_at=NOW,
            ),
        ),
        captured_at=NOW,
    )

    # 15 points remaining risk * 35
    assert (
        result.open_risk_amount
        == 525
    )

    assert (
        result.entry_risk_amount
        == 525
    )


def test_pnl_quantity_must_match_managed_position() -> None:
    service = PositionRiskSnapshotService()

    managed = make_managed_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    # No exit fills supplied:
    # calculator thinks all 65 remain open.
    with pytest.raises(
        ValueError,
        match=(
            "PnL open quantity does not match "
            "managed position open quantity"
        ),
    ):
        service.build(
            managed_position=managed,
            current_ltp=100,
            exit_fills=(),
            captured_at=NOW,
        )


def test_current_ltp_must_be_positive() -> None:
    service = PositionRiskSnapshotService()

    with pytest.raises(
        ValueError,
        match=(
            "current_ltp must be greater than zero"
        ),
    ):
        service.build(
            managed_position=(
                make_managed_position()
            ),
            current_ltp=0,
            captured_at=NOW,
        )


def test_nan_ltp_rejected() -> None:
    service = PositionRiskSnapshotService()

    with pytest.raises(
        ValueError,
        match="current_ltp must be finite",
    ):
        service.build(
            managed_position=(
                make_managed_position()
            ),
            current_ltp=math.nan,
            captured_at=NOW,
        )


def test_infinite_ltp_rejected() -> None:
    service = PositionRiskSnapshotService()

    with pytest.raises(
        ValueError,
        match="current_ltp must be finite",
    ):
        service.build(
            managed_position=(
                make_managed_position()
            ),
            current_ltp=math.inf,
            captured_at=NOW,
        )


def test_snapshot_uses_configured_stop_and_target() -> None:
    service = PositionRiskSnapshotService()

    managed = make_managed_position()

    result = service.build(
        managed_position=managed,
        current_ltp=100,
        captured_at=NOW,
    )

    assert (
        result.snapshot.stop_loss
        is managed.stop_loss
    )

    assert (
        result.snapshot.target
        is managed.target
    )


def test_snapshot_trigger_starts_none() -> None:
    service = PositionRiskSnapshotService()

    result = service.build(
        managed_position=(
            make_managed_position()
        ),
        current_ltp=85,
        captured_at=NOW,
    )

    # T05 only builds risk state.
    # Trigger evaluation comes later.
    assert (
        result.snapshot.trigger
        is RiskTriggerType.NONE
    )