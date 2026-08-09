from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
    ExecutionResult,
    OrderIntent,
    OrderIntentId,
    OrderIntentState,
    OrderType,
    TransactionType,
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


def make_signal(
    direction: SignalDirection = SignalDirection.CALL,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId("SIG-M06-001"),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=direction,
        instrument_security_id="41009",
        instrument_symbol="NIFTY50-20260811-24450-CE",
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )


def make_selected_option(
    option_type: OptionType = OptionType.CALL,
) -> SelectedOption:
    candidate = OptionCandidate(
        contract=OptionContract(
            underlying_symbol="NIFTY 50",
            symbol="NIFTY50-20260811-24450-CE",
            security_id="41009",
            option_type=option_type,
            strike=24450.0,
            expiry=EXPIRY,
            lot_size=65,
        ),
        quote=OptionQuote(
            ltp=205.0,
            bid=204.4,
            ask=204.9,
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


def make_intent() -> OrderIntent:
    return OrderIntent(
        intent_id=OrderIntentId(
            "ORD-20260807-000001"
        ),
        signal=make_signal(),
        selected_option=make_selected_option(),
        transaction_type=TransactionType.BUY,
        order_type=OrderType.LIMIT,
        quantity=65,
        limit_price=206.0,
        execution_mode=ExecutionMode.DRY_RUN,
        created_at=NOW,
    )


def test_order_intent_creation() -> None:
    intent = make_intent()

    assert (
        intent.transaction_type
        is TransactionType.BUY
    )

    assert intent.order_type is OrderType.LIMIT
    assert intent.quantity == 65
    assert intent.limit_price == 206.0

    assert (
        intent.execution_mode
        is ExecutionMode.DRY_RUN
    )

    assert (
        intent.state
        is OrderIntentState.CREATED
    )


def test_order_intent_is_immutable() -> None:
    intent = make_intent()

    with pytest.raises(FrozenInstanceError):
        intent.quantity = 130  # type: ignore[misc]


def test_empty_intent_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="order intent id cannot be empty",
    ):
        OrderIntentId(" ")


def test_zero_quantity_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="quantity must be greater than zero",
    ):
        OrderIntent(
            intent_id=OrderIntentId("TEST"),
            signal=make_signal(),
            selected_option=make_selected_option(),
            transaction_type=TransactionType.BUY,
            order_type=OrderType.LIMIT,
            quantity=0,
            limit_price=206.0,
            execution_mode=ExecutionMode.DRY_RUN,
            created_at=NOW,
        )


def test_zero_limit_price_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="limit_price must be greater than zero",
    ):
        OrderIntent(
            intent_id=OrderIntentId("TEST"),
            signal=make_signal(),
            selected_option=make_selected_option(),
            transaction_type=TransactionType.BUY,
            order_type=OrderType.LIMIT,
            quantity=65,
            limit_price=0,
            execution_mode=ExecutionMode.DRY_RUN,
            created_at=NOW,
        )


def test_signal_and_option_side_must_match() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "signal direction and selected "
            "option type must match"
        ),
    ):
        OrderIntent(
            intent_id=OrderIntentId("TEST"),
            signal=make_signal(
                SignalDirection.CALL
            ),
            selected_option=make_selected_option(
                OptionType.PUT
            ),
            transaction_type=TransactionType.BUY,
            order_type=OrderType.LIMIT,
            quantity=65,
            limit_price=206.0,
            execution_mode=ExecutionMode.DRY_RUN,
            created_at=NOW,
        )


def test_signal_security_id_must_match_selected_option() -> None:
    signal = make_signal()
    option = make_selected_option()

    mismatched_signal = TradingSignal(
        signal_id=signal.signal_id,
        trading_date=signal.trading_date,
        level=signal.level,
        direction=signal.direction,
        instrument_security_id="99999",
        instrument_symbol=signal.instrument_symbol,
        underlying_symbol=signal.underlying_symbol,
        underlying_security_id=signal.underlying_security_id,
        underlying_price=signal.underlying_price,
        level_price=signal.level_price,
        reason=signal.reason,
        state=signal.state,
        generated_at=signal.generated_at,
        is_reentry=signal.is_reentry,
        strategy_version=signal.strategy_version,
    )

    with pytest.raises(
        ValueError,
        match=(
            "signal instrument security ID and selected "
            "option security ID must match"
        ),
    ):
        OrderIntent(
            intent_id=OrderIntentId("TEST-SECURITY-MISMATCH"),
            signal=mismatched_signal,
            selected_option=option,
            transaction_type=TransactionType.BUY,
            order_type=OrderType.LIMIT,
            quantity=65,
            limit_price=206.0,
            execution_mode=ExecutionMode.DRY_RUN,
            created_at=NOW,
        )


def test_signal_symbol_must_match_selected_option() -> None:
    signal = make_signal()
    option = make_selected_option()

    mismatched_signal = TradingSignal(
        signal_id=signal.signal_id,
        trading_date=signal.trading_date,
        level=signal.level,
        direction=signal.direction,
        instrument_security_id=signal.instrument_security_id,
        instrument_symbol="WRONG-OPTION-SYMBOL",
        underlying_symbol=signal.underlying_symbol,
        underlying_security_id=signal.underlying_security_id,
        underlying_price=signal.underlying_price,
        level_price=signal.level_price,
        reason=signal.reason,
        state=signal.state,
        generated_at=signal.generated_at,
        is_reentry=signal.is_reentry,
        strategy_version=signal.strategy_version,
    )

    with pytest.raises(
        ValueError,
        match=(
            "signal instrument symbol and selected "
            "option symbol must match"
        ),
    ):
        OrderIntent(
            intent_id=OrderIntentId("TEST-SYMBOL-MISMATCH"),
            signal=mismatched_signal,
            selected_option=option,
            transaction_type=TransactionType.BUY,
            order_type=OrderType.LIMIT,
            quantity=65,
            limit_price=206.0,
            execution_mode=ExecutionMode.DRY_RUN,
            created_at=NOW,
        )


def test_broker_order_reference() -> None:
    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="ORDER123",
    )

    assert reference.broker_name == "DHAN"
    assert reference.order_id == "ORDER123"


def test_empty_broker_order_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="order_id cannot be empty",
    ):
        BrokerOrderReference(
            broker_name="DHAN",
            order_id=" ",
        )


def test_successful_execution_requires_reference() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "successful execution must contain "
            "broker_reference"
        ),
    ):
        ExecutionResult(
            intent_id=OrderIntentId("TEST"),
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=None,
            submitted_at=NOW,
        )


def test_successful_execution_result() -> None:
    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="ORDER123",
    )

    result = ExecutionResult(
        intent_id=OrderIntentId("TEST"),
        success=True,
        status=BrokerOrderStatus.OPEN,
        broker_reference=reference,
        submitted_at=NOW,
    )

    assert result.success is True
    assert result.broker_reference is reference


def test_failed_execution_can_be_rejected() -> None:
    result = ExecutionResult(
        intent_id=OrderIntentId("TEST"),
        success=False,
        status=BrokerOrderStatus.REJECTED,
        broker_reference=None,
        submitted_at=NOW,
        message="Broker rejected order",
    )

    assert result.success is False

    assert (
        result.status
        is BrokerOrderStatus.REJECTED
    )