from datetime import date, datetime, timedelta

import pytest

from src.signals.signal_lifecycle_manager import (
    SignalLifecycleManager,
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


def make_signal() -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-20260807-K5-000001"
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
        generated_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )


def test_register_signal() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    assert manager.count() == 1

    assert (
        manager.get_state(signal.signal_id)
        is SignalState.CREATED
    )


def test_duplicate_registration_is_rejected() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    with pytest.raises(
        RuntimeError,
        match="signal already registered",
    ):
        manager.register(signal)


def test_created_to_queued() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    changed_at = (
        signal.generated_at
        + timedelta(seconds=1)
    )

    transition = manager.transition(
        signal_id=signal.signal_id,
        to_state=SignalState.QUEUED,
        changed_at=changed_at,
    )

    assert transition.from_state is SignalState.CREATED
    assert transition.to_state is SignalState.QUEUED

    assert (
        manager.get_state(signal.signal_id)
        is SignalState.QUEUED
    )


def test_queued_to_accepted() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.QUEUED,
        signal.generated_at
        + timedelta(seconds=1),
    )

    manager.transition(
        signal.signal_id,
        SignalState.ACCEPTED,
        signal.generated_at
        + timedelta(seconds=2),
    )

    assert (
        manager.get_state(signal.signal_id)
        is SignalState.ACCEPTED
    )


def test_accepted_to_consumed() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.QUEUED,
        signal.generated_at
        + timedelta(seconds=1),
    )

    manager.transition(
        signal.signal_id,
        SignalState.ACCEPTED,
        signal.generated_at
        + timedelta(seconds=2),
    )

    manager.transition(
        signal.signal_id,
        SignalState.CONSUMED,
        signal.generated_at
        + timedelta(seconds=3),
    )

    assert (
        manager.get_state(signal.signal_id)
        is SignalState.CONSUMED
    )

    assert manager.is_terminal(
        signal.signal_id
    ) is True


def test_created_can_be_rejected() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.REJECTED,
        signal.generated_at
        + timedelta(seconds=1),
        reason="eligibility rejected",
    )

    assert (
        manager.get_state(signal.signal_id)
        is SignalState.REJECTED
    )


def test_queued_can_be_rejected() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.QUEUED,
        signal.generated_at
        + timedelta(seconds=1),
    )

    manager.transition(
        signal.signal_id,
        SignalState.REJECTED,
        signal.generated_at
        + timedelta(seconds=2),
        reason="downstream validation failed",
    )

    assert (
        manager.get_state(signal.signal_id)
        is SignalState.REJECTED
    )


def test_queued_can_be_cancelled() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.QUEUED,
        signal.generated_at
        + timedelta(seconds=1),
    )

    manager.transition(
        signal.signal_id,
        SignalState.CANCELLED,
        signal.generated_at
        + timedelta(seconds=2),
    )

    assert (
        manager.get_state(signal.signal_id)
        is SignalState.CANCELLED
    )


def test_invalid_created_to_consumed_is_rejected() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    with pytest.raises(
        RuntimeError,
        match=(
            "invalid signal state transition: "
            "CREATED -> CONSUMED"
        ),
    ):
        manager.transition(
            signal.signal_id,
            SignalState.CONSUMED,
            signal.generated_at
            + timedelta(seconds=1),
        )


def test_terminal_state_cannot_transition() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.REJECTED,
        signal.generated_at
        + timedelta(seconds=1),
    )

    with pytest.raises(
        RuntimeError,
        match="invalid signal state transition",
    ):
        manager.transition(
            signal.signal_id,
            SignalState.QUEUED,
            signal.generated_at
            + timedelta(seconds=2),
        )


def test_same_state_transition_is_rejected() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    with pytest.raises(
        RuntimeError,
        match="signal already in state CREATED",
    ):
        manager.transition(
            signal.signal_id,
            SignalState.CREATED,
            signal.generated_at
            + timedelta(seconds=1),
        )


def test_history_is_preserved() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.QUEUED,
        signal.generated_at
        + timedelta(seconds=1),
    )

    manager.transition(
        signal.signal_id,
        SignalState.ACCEPTED,
        signal.generated_at
        + timedelta(seconds=2),
    )

    history = manager.get_history(
        signal.signal_id
    )

    assert len(history) == 2

    assert (
        history[0].to_state
        is SignalState.QUEUED
    )

    assert (
        history[1].to_state
        is SignalState.ACCEPTED
    )


def test_snapshot() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.QUEUED,
        signal.generated_at
        + timedelta(seconds=1),
    )

    snapshot = manager.snapshot(
        signal.signal_id
    )

    assert (
        snapshot.current_state
        is SignalState.QUEUED
    )

    assert snapshot.transition_count == 1
    assert snapshot.created_at == signal.generated_at


def test_reason_is_preserved() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    transition = manager.transition(
        signal.signal_id,
        SignalState.REJECTED,
        signal.generated_at
        + timedelta(seconds=1),
        reason="option selection failed",
    )

    assert (
        transition.reason
        == "option selection failed"
    )


def test_empty_reason_is_rejected() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    with pytest.raises(
        ValueError,
        match="reason cannot be empty",
    ):
        manager.transition(
            signal.signal_id,
            SignalState.REJECTED,
            signal.generated_at
            + timedelta(seconds=1),
            reason=" ",
        )


def test_unknown_signal_state_lookup_fails() -> None:
    manager = SignalLifecycleManager()

    with pytest.raises(
        KeyError,
        match="signal not registered",
    ):
        manager.get_state(
            SignalId("UNKNOWN")
        )


def test_clear_removes_all_signals() -> None:
    manager = SignalLifecycleManager()

    signal = make_signal()

    manager.register(signal)

    manager.clear()

    assert manager.count() == 0