from datetime import date, datetime

import pytest

from src.execution.execution_types import (
    BrokerOrderReference,
    OrderIntentId,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitReason,
    FilledPosition,
    FilledPositionId,
)
from src.execution.target_booking_policy import (
    TargetBookingMode,
    TargetBookingPolicy,
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


def make_selected_option(
    *,
    option_type: OptionType = (
        OptionType.CALL
    ),
    lot_size: int = 65,
) -> SelectedOption:
    side = (
        "CE"
        if option_type is OptionType.CALL
        else "PE"
    )

    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-"
                    f"24450-{side}"
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
                    if option_type
                    is OptionType.CALL
                    else -0.64
                ),
                calculated_at=NOW,
            ),
        ),
        selected_at=NOW,
        selection_delta_target=0.64,
    )


def make_position(
    *,
    entry_price: float = 100.0,
    quantity: int = 65,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-M06-T14"
        ),
        signal_id=SignalId(
            "SIG-M06-T14"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M06-T14"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="DHAN-M06-T14",
            )
        ),
        selected_option=(
            make_selected_option()
        ),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )


def make_builder() -> ExitPlanBuilder:
    return ExitPlanBuilder(
        target_booking_policy=(
            TargetBookingPolicy()
        )
    )


def test_near_target_builds_buffered_exit() -> None:
    builder = make_builder()

    position = make_position(
        entry_price=100.0
    )

    plan = builder.build_target_exit(
        position=position,
        mapped_target_price=129.0,
        created_at=NOW,
    )

    assert (
        plan.reason
        is ExitReason.TARGET
    )

    assert (
        plan.order_type
        is ExitOrderType.LIMIT
    )

    assert (
        plan.mapped_target_price
        == 129.0
    )

    assert (
        plan.exit_price
        == 126.0
    )

    assert plan.target_plan is not None

    assert (
        plan.target_plan.mode
        is TargetBookingMode.NEAR_KS_TARGET
    )

    assert (
        plan.target_plan.booking_zone_start
        == 126.0
    )

    assert (
        plan.target_plan.booking_zone_end
        == 129.0
    )


def test_far_target_builds_plus_30_exit() -> None:
    builder = make_builder()

    position = make_position(
        entry_price=100.0
    )

    plan = builder.build_target_exit(
        position=position,
        mapped_target_price=145.0,
        created_at=NOW,
    )

    assert (
        plan.exit_price
        == 130.0
    )

    assert plan.target_plan is not None

    assert (
        plan.target_plan.mode
        is TargetBookingMode.FIXED_30_POINTS
    )


def test_exactly_30_points_uses_near_target_rule() -> None:
    builder = make_builder()

    position = make_position(
        entry_price=100.0
    )

    plan = builder.build_target_exit(
        position=position,
        mapped_target_price=130.0,
        created_at=NOW,
    )

    assert plan.target_plan is not None

    assert (
        plan.target_plan.mode
        is TargetBookingMode.NEAR_KS_TARGET
    )

    assert (
        plan.exit_price
        == 127.0
    )


def test_actual_fill_price_drives_target() -> None:
    builder = make_builder()

    position = make_position(
        entry_price=100.65
    )

    plan = builder.build_target_exit(
        position=position,
        mapped_target_price=140.0,
        created_at=NOW,
    )

    # Distance from actual fill:
    # 140 - 100.65 = 39.35
    #
    # Therefore:
    # 100.65 + 30 = 130.65

    assert (
        plan.exit_price
        == 130.65
    )

    assert plan.target_plan is not None

    assert (
        plan.target_plan.entry_price
        == 100.65
    )


def test_position_quantity_is_preserved() -> None:
    builder = make_builder()

    position = make_position(
        quantity=130
    )

    plan = builder.build_target_exit(
        position=position,
        mapped_target_price=145,
        created_at=NOW,
    )

    assert plan.quantity == 130


def test_position_contract_identity_is_preserved() -> None:
    builder = make_builder()

    position = make_position()

    plan = builder.build_target_exit(
        position=position,
        mapped_target_price=145,
        created_at=NOW,
    )

    assert (
        plan.position_id
        == position.position_id
    )

    assert (
        plan.security_id
        == position.security_id
    )

    assert (
        plan.symbol
        == position.symbol
    )

    assert (
        plan.option_type
        is position.option_type
    )


def test_target_too_close_fails_closed() -> None:
    builder = make_builder()

    position = make_position(
        entry_price=100
    )

    with pytest.raises(
        ValueError,
        match=(
            "mapped target is too close "
            "to entry"
        ),
    ):
        builder.build_target_exit(
            position=position,
            mapped_target_price=102,
            created_at=NOW,
        )


def test_force_exit_builds_market_exit() -> None:
    builder = make_builder()

    position = make_position()

    plan = builder.build_force_exit(
        position=position,
        created_at=NOW,
    )

    assert (
        plan.reason
        is ExitReason.FORCE_EXIT
    )

    assert (
        plan.order_type
        is ExitOrderType.MARKET
    )

    assert plan.exit_price is None
    assert plan.target_plan is None
    assert plan.mapped_target_price is None


def test_stop_loss_market_exit() -> None:
    builder = make_builder()

    position = make_position()

    plan = builder.build_stop_loss_exit(
        position=position,
        created_at=NOW,
    )

    assert (
        plan.reason
        is ExitReason.STOP_LOSS
    )

    assert (
        plan.order_type
        is ExitOrderType.MARKET
    )

    assert plan.exit_price is None


def test_stop_loss_limit_exit_can_have_price() -> None:
    builder = make_builder()

    position = make_position()

    plan = builder.build_stop_loss_exit(
        position=position,
        created_at=NOW,
        order_type=ExitOrderType.LIMIT,
        exit_price=85.0,
    )

    assert (
        plan.reason
        is ExitReason.STOP_LOSS
    )

    assert (
        plan.order_type
        is ExitOrderType.LIMIT
    )

    assert (
        plan.exit_price
        == 85.0
    )


def test_limit_stop_loss_requires_price() -> None:
    builder = make_builder()

    position = make_position()

    with pytest.raises(
        ValueError,
        match=(
            "LIMIT exit requires exit_price"
        ),
    ):
        builder.build_stop_loss_exit(
            position=position,
            created_at=NOW,
            order_type=ExitOrderType.LIMIT,
            exit_price=None,
        )


def test_market_stop_loss_cannot_have_price() -> None:
    builder = make_builder()

    position = make_position()

    with pytest.raises(
        ValueError,
        match=(
            "MARKET exit cannot specify "
            "exit_price"
        ),
    ):
        builder.build_stop_loss_exit(
            position=position,
            created_at=NOW,
            order_type=ExitOrderType.MARKET,
            exit_price=85.0,
        )


def test_manual_market_exit() -> None:
    builder = make_builder()

    position = make_position()

    plan = builder.build_manual_exit(
        position=position,
        created_at=NOW,
    )

    assert (
        plan.reason
        is ExitReason.MANUAL
    )

    assert (
        plan.order_type
        is ExitOrderType.MARKET
    )


def test_manual_limit_exit() -> None:
    builder = make_builder()

    position = make_position()

    plan = builder.build_manual_exit(
        position=position,
        created_at=NOW,
        order_type=ExitOrderType.LIMIT,
        exit_price=110.0,
    )

    assert (
        plan.reason
        is ExitReason.MANUAL
    )

    assert (
        plan.order_type
        is ExitOrderType.LIMIT
    )

    assert (
        plan.exit_price
        == 110.0
    )
def test_force_exit_can_use_remaining_quantity() -> None:
    builder = make_builder()

    position = make_position(
        quantity=65
    )

    plan = builder.build_force_exit(
        position=position,
        created_at=NOW,
        quantity=35,
    )

    assert plan.quantity == 35

    assert (
        plan.reason
        is ExitReason.FORCE_EXIT
    )

    assert (
        plan.order_type
        is ExitOrderType.MARKET
    )


def test_force_exit_cannot_exceed_position_quantity() -> None:
    builder = make_builder()

    position = make_position(
        quantity=65
    )

    with pytest.raises(
        ValueError,
        match=(
            "force exit quantity cannot exceed "
            "position quantity"
        ),
    ):
        builder.build_force_exit(
            position=position,
            created_at=NOW,
            quantity=130,
        )    