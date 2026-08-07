from datetime import date, datetime

import pytest

from src.execution.execution_types import (
    BrokerOrderReference,
    OrderIntentId,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitPlan,
    ExitReason,
    FilledPosition,
    FilledPositionId,
    PositionState,
)
from src.execution.target_booking_policy import (
    TargetBookingMode,
    TargetBookingPlan,
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
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


EXPIRY = date(2026, 8, 11)

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


def make_selected_option(
    *,
    option_type: OptionType = OptionType.CALL,
    lot_size: int = 65,
) -> SelectedOption:
    side = (
        "CE"
        if option_type is OptionType.CALL
        else "PE"
    )

    candidate = OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol=(
                f"NIFTY50-20260811-24450-{side}"
            ),
            security_id="41009",
            option_type=option_type,
            strike=24450.0,
            expiry=EXPIRY,
            lot_size=lot_size,
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
            delta=(
                0.64
                if option_type is OptionType.CALL
                else -0.64
            ),
            calculated_at=NOW,
        ),
    )

    return SelectedOption(
        candidate=candidate,
        selected_at=NOW,
        selection_delta_target=0.64,
    )


def make_position(
    *,
    quantity: int = 65,
    entry_price: float = 100.0,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-001"
        ),
        signal_id=SignalId(
            "SIG-001"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-001"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="DHAN-001",
            )
        ),
        selected_option=make_selected_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )


def make_target_plan() -> TargetBookingPlan:
    return TargetBookingPlan(
        entry_price=100.0,
        mapped_target_price=129.0,
        target_distance_points=29.0,
        executable_target_price=126.0,
        booking_zone_start=126.0,
        booking_zone_end=129.0,
        mode=TargetBookingMode.NEAR_KS_TARGET,
        tick_size=0.05,
    )


def test_filled_position_creation() -> None:
    position = make_position()

    assert (
        position.state
        is PositionState.OPEN
    )

    assert position.quantity == 65
    assert position.entry_price == 100.0
    assert position.security_id == "41009"
    assert position.lot_size == 65
    assert position.lot_count == 1


def test_two_lot_position() -> None:
    position = make_position(
        quantity=130
    )

    assert position.lot_count == 2


def test_position_quantity_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "position quantity must be "
            "greater than zero"
        ),
    ):
        make_position(
            quantity=0
        )


def test_position_quantity_must_match_lot_size() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "position quantity must be a multiple"
        ),
    ):
        make_position(
            quantity=100
        )


def test_entry_price_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "entry_price must be greater than zero"
        ),
    ):
        make_position(
            entry_price=0
        )


def test_empty_position_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "filled position id cannot be empty"
        ),
    ):
        FilledPositionId(" ")


def test_target_exit_plan_creation() -> None:
    position = make_position()

    target_plan = make_target_plan()

    exit_plan = ExitPlan(
        position_id=position.position_id,
        security_id=position.security_id,
        symbol=position.symbol,
        option_type=position.option_type,
        quantity=position.quantity,
        reason=ExitReason.TARGET,
        order_type=ExitOrderType.LIMIT,
        mapped_target_price=129.0,
        target_plan=target_plan,
        exit_price=126.0,
        created_at=NOW,
    )

    assert (
        exit_plan.reason
        is ExitReason.TARGET
    )

    assert (
        exit_plan.exit_price
        == 126.0
    )

    assert (
        exit_plan.target_plan
        is target_plan
    )


def test_target_exit_requires_target_plan() -> None:
    position = make_position()

    with pytest.raises(
        ValueError,
        match=(
            "target exit requires target_plan"
        ),
    ):
        ExitPlan(
            position_id=position.position_id,
            security_id=position.security_id,
            symbol=position.symbol,
            option_type=position.option_type,
            quantity=position.quantity,
            reason=ExitReason.TARGET,
            order_type=ExitOrderType.LIMIT,
            mapped_target_price=129.0,
            target_plan=None,
            exit_price=126.0,
            created_at=NOW,
        )


def test_target_exit_requires_mapped_target_price() -> None:
    position = make_position()

    with pytest.raises(
        ValueError,
        match=(
            "target exit requires mapped_target_price"
        ),
    ):
        ExitPlan(
            position_id=position.position_id,
            security_id=position.security_id,
            symbol=position.symbol,
            option_type=position.option_type,
            quantity=position.quantity,
            reason=ExitReason.TARGET,
            order_type=ExitOrderType.LIMIT,
            mapped_target_price=None,
            target_plan=make_target_plan(),
            exit_price=126.0,
            created_at=NOW,
        )


def test_target_exit_price_must_match_target_plan() -> None:
    position = make_position()

    with pytest.raises(
        ValueError,
        match=(
            "exit_price must match target plan"
        ),
    ):
        ExitPlan(
            position_id=position.position_id,
            security_id=position.security_id,
            symbol=position.symbol,
            option_type=position.option_type,
            quantity=position.quantity,
            reason=ExitReason.TARGET,
            order_type=ExitOrderType.LIMIT,
            mapped_target_price=129.0,
            target_plan=make_target_plan(),
            exit_price=127.0,
            created_at=NOW,
        )


def test_force_exit_can_use_market_order() -> None:
    position = make_position()

    exit_plan = ExitPlan(
        position_id=position.position_id,
        security_id=position.security_id,
        symbol=position.symbol,
        option_type=position.option_type,
        quantity=position.quantity,
        reason=ExitReason.FORCE_EXIT,
        order_type=ExitOrderType.MARKET,
        mapped_target_price=None,
        target_plan=None,
        exit_price=None,
        created_at=NOW,
    )

    assert (
        exit_plan.reason
        is ExitReason.FORCE_EXIT
    )

    assert (
        exit_plan.order_type
        is ExitOrderType.MARKET
    )


def test_stop_loss_exit_without_target_plan() -> None:
    position = make_position()

    exit_plan = ExitPlan(
        position_id=position.position_id,
        security_id=position.security_id,
        symbol=position.symbol,
        option_type=position.option_type,
        quantity=position.quantity,
        reason=ExitReason.STOP_LOSS,
        order_type=ExitOrderType.MARKET,
        mapped_target_price=None,
        target_plan=None,
        exit_price=None,
        created_at=NOW,
    )

    assert (
        exit_plan.reason
        is ExitReason.STOP_LOSS
    )


def test_non_target_exit_cannot_have_target_plan() -> None:
    position = make_position()

    with pytest.raises(
        ValueError,
        match=(
            "non-target exit cannot contain target_plan"
        ),
    ):
        ExitPlan(
            position_id=position.position_id,
            security_id=position.security_id,
            symbol=position.symbol,
            option_type=position.option_type,
            quantity=position.quantity,
            reason=ExitReason.FORCE_EXIT,
            order_type=ExitOrderType.MARKET,
            mapped_target_price=None,
            target_plan=make_target_plan(),
            exit_price=None,
            created_at=NOW,
        )