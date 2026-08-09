from datetime import date, datetime, timedelta

import pytest

from src.execution.execution_types import (
    ExecutionMode,
    OrderIntent,
    OrderIntentId,
    OrderType,
    TransactionType,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
    IdempotencyKey,
    IdempotencyState,
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

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


def make_signal(
    signal_id: str = "SIG-M06-T09",
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            signal_id
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        instrument_security_id="41009",
        instrument_symbol="NIFTY50-20260811-24450-CE",
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500,
        level_price=24500,
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
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=205,
                bid=204.4,
                ask=204.9,
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
    intent_id: str = "ORD-M06-T09",
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
        limit_price=206,
        execution_mode=ExecutionMode.DRY_RUN,
        created_at=NOW,
    )


def test_key_from_signal_id() -> None:
    signal = make_signal()

    key = IdempotencyKey.from_signal_id(
        signal.signal_id
    )

    assert (
        key.value
        == "SIGNAL:SIG-M06-T09"
    )


def test_empty_key_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="idempotency key cannot be empty",
    ):
        IdempotencyKey(" ")


def test_first_reservation_is_acquired() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    result = guard.reserve(
        key=key,
        created_at=NOW,
    )

    assert result.acquired is True

    record = guard.get(
        key
    )

    assert record is not None

    assert (
        record.state
        is IdempotencyState.RESERVED
    )


def test_duplicate_reservation_is_blocked() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    first = guard.reserve(
        key=key,
        created_at=NOW,
    )

    second = guard.reserve(
        key=key,
        created_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert first.acquired is True
    assert second.acquired is False

    assert second.existing_record is not None

    assert (
        second.existing_record.state
        is IdempotencyState.RESERVED
    )


def test_different_signals_are_independent() -> None:
    guard = DuplicateOrderGuard()

    first = guard.reserve(
        key=IdempotencyKey(
            "SIGNAL:001"
        ),
        created_at=NOW,
    )

    second = guard.reserve(
        key=IdempotencyKey(
            "SIGNAL:002"
        ),
        created_at=NOW,
    )

    assert first.acquired is True
    assert second.acquired is True
    assert guard.count() == 2


def test_attach_intent() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    intent = make_intent()

    record = guard.attach_intent(
        key=key,
        intent=intent,
        changed_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert (
        record.intent_id
        == intent.intent_id.value
    )

    assert (
        record.state
        is IdempotencyState.RESERVED
    )


def test_second_intent_cannot_be_attached() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent(
        key=key,
        intent=make_intent(
            "ORD-001"
        ),
        changed_at=NOW,
    )

    with pytest.raises(
        RuntimeError,
        match="already has an intent",
    ):
        guard.attach_intent(
            key=key,
            intent=make_intent(
                "ORD-002"
            ),
            changed_at=NOW,
        )


def test_mark_submitted() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent(
        key=key,
        intent=make_intent(),
        changed_at=NOW,
    )

    record = guard.mark_submitted(
        key=key,
        changed_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert (
        record.state
        is IdempotencyState.SUBMITTED
    )


def test_cannot_submit_without_intent() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    with pytest.raises(
        RuntimeError,
        match="without attached intent",
    ):
        guard.mark_submitted(
            key=key,
            changed_at=NOW,
        )


def test_submitted_key_blocks_duplicate() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent(
        key=key,
        intent=make_intent(),
        changed_at=NOW,
    )

    guard.mark_submitted(
        key=key,
        changed_at=NOW,
    )

    duplicate = guard.reserve(
        key=key,
        created_at=(
            NOW
            + timedelta(seconds=5)
        ),
    )

    assert duplicate.acquired is False

    assert (
        duplicate.existing_record.state
        is IdempotencyState.SUBMITTED
    )


def test_completed_key_blocks_duplicate() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent(
        key=key,
        intent=make_intent(),
        changed_at=NOW,
    )

    guard.mark_submitted(
        key=key,
        changed_at=NOW,
    )

    guard.mark_completed(
        key=key,
        changed_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert guard.is_blocked(
        key
    ) is True

    duplicate = guard.reserve(
        key=key,
        created_at=(
            NOW
            + timedelta(seconds=2)
        ),
    )

    assert duplicate.acquired is False


def test_reserved_key_can_be_released() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    record = guard.release(
        key=key,
        changed_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert (
        record.state
        is IdempotencyState.RELEASED
    )

    assert guard.is_blocked(
        key
    ) is False


def test_released_key_can_be_reserved_again() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.release(
        key=key,
        changed_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    result = guard.reserve(
        key=key,
        created_at=(
            NOW
            + timedelta(seconds=2)
        ),
    )

    assert result.acquired is True

    assert (
        guard.get(key).state
        is IdempotencyState.RESERVED
    )


def test_submitted_key_cannot_be_released() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent(
        key=key,
        intent=make_intent(),
        changed_at=NOW,
    )

    guard.mark_submitted(
        key=key,
        changed_at=NOW,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "only RESERVED idempotency key "
            "can be released"
        ),
    ):
        guard.release(
            key=key,
            changed_at=NOW,
        )


def test_completed_key_cannot_be_released() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "SIGNAL:001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent(
        key=key,
        intent=make_intent(),
        changed_at=NOW,
    )

    guard.mark_completed(
        key=key,
        changed_at=NOW,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "only RESERVED idempotency key "
            "can be released"
        ),
    ):
        guard.release(
            key=key,
            changed_at=NOW,
        )


def test_unknown_key_raises() -> None:
    guard = DuplicateOrderGuard()

    with pytest.raises(
        KeyError,
        match="idempotency key not reserved",
    ):
        guard.mark_completed(
            key=IdempotencyKey(
                "SIGNAL:UNKNOWN"
            ),
            changed_at=NOW,
        )


def test_clear() -> None:
    guard = DuplicateOrderGuard()

    guard.reserve(
        key=IdempotencyKey(
            "SIGNAL:001"
        ),
        created_at=NOW,
    )

    guard.clear()

    assert guard.count() == 0
def test_submitted_key_can_be_released_after_reconciliation() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "EXIT_POSITION:POS-001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent_id(
        key=key,
        intent_id="EXIT-001",
        changed_at=NOW,
    )

    guard.mark_submitted(
        key=key,
        changed_at=NOW,
    )

    record = (
        guard.release_after_reconciliation(
            key=key,
            changed_at=(
                NOW
                + timedelta(seconds=1)
            ),
        )
    )

    assert (
        record.state
        is IdempotencyState.RELEASED
    )

    assert guard.is_blocked(
        key
    ) is False


def test_reserved_key_cannot_use_reconciliation_release() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "EXIT_POSITION:POS-001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "only SUBMITTED idempotency key "
            "can be reconciliation-released"
        ),
    ):
        guard.release_after_reconciliation(
            key=key,
            changed_at=NOW,
        )


def test_completed_key_cannot_use_reconciliation_release() -> None:
    guard = DuplicateOrderGuard()

    key = IdempotencyKey(
        "EXIT_POSITION:POS-001"
    )

    guard.reserve(
        key=key,
        created_at=NOW,
    )

    guard.attach_intent_id(
        key=key,
        intent_id="EXIT-001",
        changed_at=NOW,
    )

    guard.mark_submitted(
        key=key,
        changed_at=NOW,
    )

    guard.mark_completed(
        key=key,
        changed_at=NOW,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "only SUBMITTED idempotency key "
            "can be reconciliation-released"
        ),
    ):
        guard.release_after_reconciliation(
            key=key,
            changed_at=NOW,
        )    