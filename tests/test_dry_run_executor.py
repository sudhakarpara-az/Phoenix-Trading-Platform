from datetime import date, datetime

from src.execution.dry_run_executor import (
    DryRunExecutor,
)
from src.execution.execution_types import (
    BrokerOrderStatus,
    ExecutionMode,
    OrderIntent,
    OrderIntentId,
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
from src.strategy.strategy_types import (
    EntryLevel,
)


TRADING_DATE = date(2026, 8, 7)

EXPIRY = date(2026, 8, 11)

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


def make_signal() -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-M06-T10"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
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


def make_selected_option() -> SelectedOption:
    candidate = OptionCandidate(
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
            ltp=205.0,
            bid=204.40,
            ask=204.90,
            volume=1000,
            open_interest=50000,
            received_at=NOW,
        ),
        greeks=OptionGreeks(
            delta=0.64,
            calculated_at=NOW,
        ),
    )

    return SelectedOption(
        candidate=candidate,
        selected_at=NOW,
        selection_delta_target=0.64,
    )


def make_intent(
    *,
    intent_id: str = "ORD-M06-T10",
) -> OrderIntent:
    return OrderIntent(
        intent_id=OrderIntentId(
            intent_id
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


def test_dry_run_returns_success() -> None:
    executor = DryRunExecutor()

    result = executor.execute(
        intent=make_intent(),
        executed_at=NOW,
    )

    assert result.success is True


def test_dry_run_returns_open_not_filled() -> None:
    executor = DryRunExecutor()

    result = executor.execute(
        intent=make_intent(),
        executed_at=NOW,
    )

    assert (
        result.status
        is BrokerOrderStatus.OPEN
    )


def test_dry_run_reference_is_not_real_broker() -> None:
    executor = DryRunExecutor()

    result = executor.execute(
        intent=make_intent(),
        executed_at=NOW,
    )

    assert result.broker_reference is not None

    assert (
        result.broker_reference.broker_name
        == "DRY_RUN"
    )

    assert (
        result.broker_reference.order_id
        == "DRY-ORD-M06-T10"
    )


def test_dry_run_records_order() -> None:
    executor = DryRunExecutor()

    intent = make_intent()

    executor.execute(
        intent=intent,
        executed_at=NOW,
    )

    assert executor.count() == 1

    records = executor.records()

    assert len(records) == 1

    record = records[0]

    assert (
        record.intent_id
        == "ORD-M06-T10"
    )

    assert (
        record.signal_id
        == "SIG-M06-T10"
    )

    assert (
        record.security_id
        == "41009"
    )

    assert (
        record.symbol
        == "NIFTY50-20260811-24450-CE"
    )

    assert record.quantity == 65

    assert (
        record.limit_price
        == 206.0
    )

    assert (
        record.simulated_at
        == NOW
    )


def test_dry_run_message_states_no_broker_order() -> None:
    executor = DryRunExecutor()

    result = executor.execute(
        intent=make_intent(),
        executed_at=NOW,
    )

    assert result.message is not None

    assert (
        "no broker order submitted"
        in result.message
    )


def test_multiple_intents_are_audited() -> None:
    executor = DryRunExecutor()

    first = make_intent(
        intent_id="ORD-M06-T10-001"
    )

    second = make_intent(
        intent_id="ORD-M06-T10-002"
    )

    executor.execute(
        intent=first,
        executed_at=NOW,
    )

    executor.execute(
        intent=second,
        executed_at=NOW,
    )

    assert executor.count() == 2

    records = executor.records()

    assert (
        records[0].intent_id
        == "ORD-M06-T10-001"
    )

    assert (
        records[1].intent_id
        == "ORD-M06-T10-002"
    )


def test_records_returns_tuple() -> None:
    executor = DryRunExecutor()

    executor.execute(
        intent=make_intent(),
        executed_at=NOW,
    )

    records = executor.records()

    assert isinstance(
        records,
        tuple,
    )


def test_clear_removes_all_audit_records() -> None:
    executor = DryRunExecutor()

    executor.execute(
        intent=make_intent(),
        executed_at=NOW,
    )

    assert executor.count() == 1

    executor.clear()

    assert executor.count() == 0

    assert (
        executor.records()
        == ()
    )