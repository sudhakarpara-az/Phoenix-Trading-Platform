from datetime import date, datetime

import pytest

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
from src.execution.filled_position_builder import (
    FilledPositionBuilder,
)
from src.execution.position_exit_types import (
    PositionState,
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

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)

FILLED_AT = datetime(
    2026,
    8,
    7,
    14,
    30,
    5,
)


def make_signal() -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-M06-T15"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )


def make_selected_option() -> SelectedOption:
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


def make_intent(
    *,
    quantity: int = 65,
    limit_price: float = 101.0,
) -> OrderIntent:
    return OrderIntent(
        intent_id=OrderIntentId(
            "ORD-M06-T15"
        ),
        signal=make_signal(),
        selected_option=make_selected_option(),
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit_price,
        execution_mode=ExecutionMode.LIVE,
        created_at=NOW,
    )


def make_filled_snapshot(
    *,
    quantity: int = 65,
    filled_quantity: int = 65,
    average_price: float | None = 100.65,
    status: BrokerOrderStatus = (
        BrokerOrderStatus.FILLED
    ),
    broker_name: str = "DHAN",
) -> BrokerOrderSnapshot:
    return BrokerOrderSnapshot(
        broker_reference=(
            BrokerOrderReference(
                broker_name=broker_name,
                order_id="DHAN-001",
            )
        ),
        status=status,
        quantity=quantity,
        filled_quantity=filled_quantity,
        average_price=average_price,
        updated_at=FILLED_AT,
    )


def test_build_filled_position() -> None:
    builder = FilledPositionBuilder()

    intent = make_intent()

    snapshot = make_filled_snapshot()

    position = builder.build(
        intent=intent,
        broker_snapshot=snapshot,
    )

    assert (
        position.state
        is PositionState.OPEN
    )

    assert (
        position.signal_id
        == intent.signal.signal_id
    )

    assert (
        position.entry_intent_id
        == intent.intent_id
    )

    assert (
        position.entry_broker_reference
        == snapshot.broker_reference
    )

    assert (
        position.selected_option
        is intent.selected_option
    )

    assert (
        position.level
        is EntryLevel.K5
    )


def test_broker_average_price_becomes_entry_price() -> None:
    builder = FilledPositionBuilder()

    position = builder.build(
        intent=make_intent(
            limit_price=101.0
        ),
        broker_snapshot=(
            make_filled_snapshot(
                average_price=100.65
            )
        ),
    )

    assert (
        position.entry_price
        == 100.65
    )

    assert (
        position.entry_price
        != 101.0
    )


def test_option_ltp_is_not_used_as_entry_price() -> None:
    builder = FilledPositionBuilder()

    intent = make_intent()

    assert (
        intent.selected_option.ltp
        == 100.0
    )

    position = builder.build(
        intent=intent,
        broker_snapshot=(
            make_filled_snapshot(
                average_price=100.65
            )
        ),
    )

    assert (
        position.entry_price
        == 100.65
    )

    assert (
        position.entry_price
        != intent.selected_option.ltp
    )


def test_filled_time_defaults_to_broker_update_time() -> None:
    builder = FilledPositionBuilder()

    position = builder.build(
        intent=make_intent(),
        broker_snapshot=(
            make_filled_snapshot()
        ),
    )

    assert (
        position.filled_at
        == FILLED_AT
    )


def test_explicit_created_time_can_override_fill_time() -> None:
    builder = FilledPositionBuilder()

    custom = datetime(
        2026,
        8,
        7,
        14,
        31,
    )

    position = builder.build(
        intent=make_intent(),
        broker_snapshot=(
            make_filled_snapshot()
        ),
        created_at=custom,
    )

    assert position.filled_at == custom


def test_quantity_is_preserved() -> None:
    builder = FilledPositionBuilder()

    position = builder.build(
        intent=make_intent(
            quantity=130
        ),
        broker_snapshot=(
            make_filled_snapshot(
                quantity=130,
                filled_quantity=130,
            )
        ),
    )

    assert position.quantity == 130
    assert position.lot_count == 2


def test_non_filled_order_is_rejected() -> None:
    builder = FilledPositionBuilder()

    with pytest.raises(
        ValueError,
        match=(
            "can only be built from FILLED"
        ),
    ):
        builder.build(
            intent=make_intent(),
            broker_snapshot=(
                make_filled_snapshot(
                    status=BrokerOrderStatus.OPEN
                )
            ),
        )


def test_partially_filled_order_is_rejected() -> None:
    builder = FilledPositionBuilder()

    with pytest.raises(
        ValueError,
        match=(
            "can only be built from FILLED"
        ),
    ):
        builder.build(
            intent=make_intent(),
            broker_snapshot=(
                make_filled_snapshot(
                    status=(
                        BrokerOrderStatus
                        .PARTIALLY_FILLED
                    ),
                    filled_quantity=30,
                )
            ),
        )


def test_broker_quantity_must_match_intent() -> None:
    builder = FilledPositionBuilder()

    with pytest.raises(
        ValueError,
        match=(
            "broker order quantity does not match"
        ),
    ):
        builder.build(
            intent=make_intent(
                quantity=65
            ),
            broker_snapshot=(
                make_filled_snapshot(
                    quantity=130,
                    filled_quantity=130,
                )
            ),
        )


def test_filled_quantity_must_match_intent() -> None:
    builder = FilledPositionBuilder()

    with pytest.raises(
        ValueError,
        match=(
            "filled quantity does not match"
        ),
    ):
        builder.build(
            intent=make_intent(
                quantity=65
            ),
            broker_snapshot=(
                make_filled_snapshot(
                    quantity=65,
                    filled_quantity=30,
                )
            ),
        )


def test_missing_average_price_is_rejected() -> None:
    builder = FilledPositionBuilder()

    with pytest.raises(
        ValueError,
        match=(
            "must contain average fill price"
        ),
    ):
        builder.build(
            intent=make_intent(),
            broker_snapshot=(
                make_filled_snapshot(
                    average_price=None
                )
            ),
        )


def test_dry_run_snapshot_cannot_create_real_position() -> None:
    builder = FilledPositionBuilder()

    with pytest.raises(
        ValueError,
        match=(
            "dry-run order cannot create "
            "real filled position"
        ),
    ):
        builder.build(
            intent=make_intent(),
            broker_snapshot=(
                make_filled_snapshot(
                    broker_name="DRY_RUN"
                )
            ),
        )


def test_position_ids_are_unique() -> None:
    builder = FilledPositionBuilder()

    first = builder.build(
        intent=make_intent(),
        broker_snapshot=(
            make_filled_snapshot()
        ),
    )

    second = builder.build(
        intent=make_intent(),
        broker_snapshot=(
            make_filled_snapshot()
        ),
    )

    assert (
        first.position_id
        != second.position_id
    )


def test_position_id_format() -> None:
    builder = FilledPositionBuilder()

    position = builder.build(
        intent=make_intent(),
        broker_snapshot=(
            make_filled_snapshot()
        ),
    )

    assert (
        position.position_id.value
        == "POS-20260807-000001"
    )