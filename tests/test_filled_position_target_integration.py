from datetime import date, datetime

from src.execution.broker_execution_provider import (
    BrokerOrderSnapshot,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
    OrderIntent,
    OrderIntentId,
    OrderType,
    TransactionType,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.filled_position_builder import (
    FilledPositionBuilder,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitReason,
    PositionState,
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
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


TRADING_DATE = date(
    2026,
    8,
    7,
)

EXPIRY = date(
    2026,
    8,
    11,
)

SIGNAL_TIME = datetime(
    2026,
    8,
    7,
    14,
    30,
)

FILL_TIME = datetime(
    2026,
    8,
    7,
    14,
    30,
    5,
)


def make_signal(
    *,
    signal_id: str = "SIG-M06-T16",
    direction: SignalDirection = SignalDirection.CALL,
    level: EntryLevel = EntryLevel.K5,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            signal_id
        ),
        trading_date=TRADING_DATE,
        level=level,
        direction=direction,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=SIGNAL_TIME,
    )


def make_selected_option(
    *,
    option_type: OptionType = OptionType.CALL,
    security_id: str = "41009",
    strike: float = 24450.0,
    ltp: float = 100.0,
    delta: float = 0.64,
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
                    f"{int(strike)}-{side}"
                ),
                security_id=security_id,
                option_type=option_type,
                strike=strike,
                expiry=EXPIRY,
                lot_size=lot_size,
            ),
            quote=OptionQuote(
                ltp=ltp,
                bid=ltp - 0.05,
                ask=ltp + 0.05,
                volume=10000,
                open_interest=50000,
                received_at=SIGNAL_TIME,
            ),
            greeks=OptionGreeks(
                delta=delta,
                gamma=0.001,
                theta=-4.0,
                vega=6.0,
                implied_volatility=12.0,
                calculated_at=SIGNAL_TIME,
            ),
        ),
        selected_at=SIGNAL_TIME,
        selection_delta_target=0.64,
    )


def make_intent(
    *,
    signal: TradingSignal | None = None,
    selected_option: SelectedOption | None = None,
    quantity: int = 65,
    limit_price: float = 101.0,
) -> OrderIntent:
    return OrderIntent(
        intent_id=OrderIntentId(
            "ORD-M06-T16"
        ),
        signal=(
            signal
            or make_signal()
        ),
        selected_option=(
            selected_option
            or make_selected_option()
        ),
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit_price,
        execution_mode=ExecutionMode.LIVE,
        created_at=SIGNAL_TIME,
    )


def make_filled_snapshot(
    *,
    quantity: int = 65,
    average_price: float = 100.65,
    order_id: str = "DHAN-T16-001",
) -> BrokerOrderSnapshot:
    return BrokerOrderSnapshot(
        broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id=order_id,
            )
        ),
        status=BrokerOrderStatus.FILLED,
        quantity=quantity,
        filled_quantity=quantity,
        average_price=average_price,
        updated_at=FILL_TIME,
    )


def make_exit_builder() -> ExitPlanBuilder:
    return ExitPlanBuilder(
        target_booking_policy=(
            TargetBookingPolicy()
        )
    )


def test_filled_order_becomes_open_position() -> None:
    intent = make_intent()

    snapshot = make_filled_snapshot(
        average_price=100.65
    )

    position = FilledPositionBuilder().build(
        intent=intent,
        broker_snapshot=snapshot,
    )

    assert (
        position.state
        is PositionState.OPEN
    )

    assert (
        position.entry_price
        == 100.65
    )

    assert (
        position.quantity
        == 65
    )

    assert (
        position.security_id
        == "41009"
    )


def test_entry_price_comes_from_broker_average_not_option_ltp() -> None:
    selected_option = (
        make_selected_option(
            ltp=100.0
        )
    )

    intent = make_intent(
        selected_option=selected_option,
        limit_price=101.0,
    )

    position = (
        FilledPositionBuilder()
        .build(
            intent=intent,
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=100.65
                )
            ),
        )
    )

    assert (
        selected_option.ltp
        == 100.0
    )

    assert (
        intent.limit_price
        == 101.0
    )

    assert (
        position.entry_price
        == 100.65
    )


def test_far_target_uses_actual_fill_plus_30() -> None:
    intent = make_intent()

    position = (
        FilledPositionBuilder()
        .build(
            intent=intent,
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=100.65
                )
            ),
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=140.0,
            created_at=FILL_TIME,
        )
    )

    # Actual entry:
    # 100.65
    #
    # Mapped target:
    # 140.00
    #
    # Distance:
    # 39.35
    #
    # > 30
    #
    # Effective target:
    # 100.65 + 30 = 130.65

    assert (
        exit_plan.reason
        is ExitReason.TARGET
    )

    assert (
        exit_plan.order_type
        is ExitOrderType.LIMIT
    )

    assert (
        exit_plan.exit_price
        == 130.65
    )

    assert (
        exit_plan.target_plan
        is not None
    )

    assert (
        exit_plan.target_plan.mode
        is TargetBookingMode.FIXED_30_POINTS
    )

    assert (
        exit_plan.target_plan.entry_price
        == 100.65
    )

    assert (
        exit_plan.target_plan
        .mapped_target_price
        == 140.0
    )


def test_near_target_uses_three_point_buffer() -> None:
    intent = make_intent()

    position = (
        FilledPositionBuilder()
        .build(
            intent=intent,
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=100.0
                )
            ),
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=129.0,
            created_at=FILL_TIME,
        )
    )

    # Your rule:
    #
    # Entry = 100
    # mapped target = 129
    # distance = 29
    #
    # <= 30
    #
    # booking trigger:
    # 129 - 3 = 126

    assert (
        exit_plan.exit_price
        == 126.0
    )

    assert (
        exit_plan.target_plan
        is not None
    )

    assert (
        exit_plan.target_plan.mode
        is TargetBookingMode.NEAR_KS_TARGET
    )

    assert (
        exit_plan.target_plan
        .booking_zone_start
        == 126.0
    )

    assert (
        exit_plan.target_plan
        .booking_zone_end
        == 129.0
    )


def test_exactly_30_points_uses_buffered_ks_target() -> None:
    position = (
        FilledPositionBuilder()
        .build(
            intent=make_intent(),
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=100.0
                )
            ),
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=130.0,
            created_at=FILL_TIME,
        )
    )

    assert (
        exit_plan.target_plan
        is not None
    )

    assert (
        exit_plan.target_plan.mode
        is TargetBookingMode.NEAR_KS_TARGET
    )

    assert (
        exit_plan.exit_price
        == 127.0
    )


def test_just_over_30_points_uses_fixed_30() -> None:
    position = (
        FilledPositionBuilder()
        .build(
            intent=make_intent(),
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=100.0
                )
            ),
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=130.05,
            created_at=FILL_TIME,
        )
    )

    assert (
        exit_plan.target_plan
        is not None
    )

    assert (
        exit_plan.target_plan.mode
        is TargetBookingMode.FIXED_30_POINTS
    )

    assert (
        exit_plan.exit_price
        == 130.0
    )


def test_two_lot_position_preserves_full_exit_quantity() -> None:
    intent = make_intent(
        quantity=130
    )

    snapshot = make_filled_snapshot(
        quantity=130,
        average_price=100.0,
    )

    position = (
        FilledPositionBuilder()
        .build(
            intent=intent,
            broker_snapshot=snapshot,
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=145,
            created_at=FILL_TIME,
        )
    )

    assert (
        position.quantity
        == 130
    )

    assert (
        position.lot_count
        == 2
    )

    assert (
        exit_plan.quantity
        == 130
    )


def test_contract_identity_survives_full_lifecycle() -> None:
    selected_option = make_selected_option(
        security_id="41009",
        strike=24450,
    )

    intent = make_intent(
        selected_option=selected_option
    )

    snapshot = make_filled_snapshot()

    position = (
        FilledPositionBuilder()
        .build(
            intent=intent,
            broker_snapshot=snapshot,
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=140,
            created_at=FILL_TIME,
        )
    )

    assert (
        intent.selected_option.security_id
        == "41009"
    )

    assert (
        position.security_id
        == "41009"
    )

    assert (
        exit_plan.security_id
        == "41009"
    )

    assert (
        exit_plan.symbol
        == position.symbol
    )


def test_signal_and_entry_level_survive_position_creation() -> None:
    signal = make_signal(
        signal_id="SIG-K5-T16",
        level=EntryLevel.K5,
    )

    intent = make_intent(
        signal=signal
    )

    position = (
        FilledPositionBuilder()
        .build(
            intent=intent,
            broker_snapshot=(
                make_filled_snapshot()
            ),
        )
    )

    assert (
        position.signal_id
        == signal.signal_id
    )

    assert (
        position.level
        is EntryLevel.K5
    )

    assert (
        position.entry_intent_id
        == intent.intent_id
    )


def test_put_position_can_build_target_exit() -> None:
    signal = make_signal(
        signal_id="SIG-PUT-T16",
        direction=SignalDirection.PUT,
    )

    selected_option = (
        make_selected_option(
            option_type=OptionType.PUT,
            security_id="41019",
            strike=24650,
            ltp=100,
            delta=-0.64,
        )
    )

    intent = make_intent(
        signal=signal,
        selected_option=selected_option,
    )

    position = (
        FilledPositionBuilder()
        .build(
            intent=intent,
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=100
                )
            ),
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=129,
            created_at=FILL_TIME,
        )
    )

    assert (
        position.option_type
        is OptionType.PUT
    )

    assert (
        exit_plan.option_type
        is OptionType.PUT
    )

    assert (
        exit_plan.exit_price
        == 126
    )


def test_far_target_booking_zone_is_fixed_price() -> None:
    position = (
        FilledPositionBuilder()
        .build(
            intent=make_intent(),
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=100
                )
            ),
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=145,
            created_at=FILL_TIME,
        )
    )

    assert (
        exit_plan.target_plan
        is not None
    )

    assert (
        exit_plan.target_plan
        .booking_zone_start
        == 130
    )

    assert (
        exit_plan.target_plan
        .booking_zone_end
        == 130
    )


def test_near_target_preserves_original_ks_target() -> None:
    position = (
        FilledPositionBuilder()
        .build(
            intent=make_intent(),
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=100
                )
            ),
        )
    )

    exit_plan = (
        make_exit_builder()
        .build_target_exit(
            position=position,
            mapped_target_price=129,
            created_at=FILL_TIME,
        )
    )

    assert (
        exit_plan.mapped_target_price
        == 129
    )

    assert (
        exit_plan.exit_price
        == 126
    )

    assert (
        exit_plan.mapped_target_price
        != exit_plan.exit_price
    )