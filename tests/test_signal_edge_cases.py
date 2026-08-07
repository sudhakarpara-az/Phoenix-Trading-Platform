"""
M04 failure and edge-case tests.

These tests stress the Phoenix signal-generation subsystem
without adding new production behavior.
"""

from datetime import date, datetime, timedelta

import pytest

from src.signals.duplicate_signal_guard import (
    DuplicateSignalGuard,
)
from src.signals.eligibility_policy import (
    EligibilityContext,
    EligibilityReason,
    SignalEligibilityPolicy,
)
from src.signals.level_lock_manager import (
    LevelLockManager,
)
from src.signals.reentry_state_manager import (
    ReentryStateManager,
)
from src.signals.signal_builder import SignalBuilder
from src.signals.signal_engine import (
    SignalEngine,
    SignalEngineReason,
)
from src.signals.signal_lifecycle_manager import (
    SignalLifecycleManager,
)
from src.signals.signal_queue import SignalQueue
from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalState,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    LevelEvent,
    LevelEventType,
    StrategySessionState,
)


TRADING_DATE = date(2026, 8, 7)


def make_engine(
    suppression_seconds: float = 5.0,
) -> SignalEngine:
    return SignalEngine(
        eligibility_policy=SignalEligibilityPolicy(),
        duplicate_guard=DuplicateSignalGuard(
            suppression_seconds=suppression_seconds
        ),
        level_lock_manager=LevelLockManager(),
        reentry_manager=ReentryStateManager(),
        signal_builder=SignalBuilder(),
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
    )


def make_context(
    *,
    trading_date: date = TRADING_DATE,
    session_state: StrategySessionState = (
        StrategySessionState.MONITORING
    ),
    trading_enabled: bool = True,
    platform_halted: bool = False,
) -> EligibilityContext:
    return EligibilityContext(
        trading_date=trading_date,
        session_state=session_state,
        trading_enabled=trading_enabled,
        platform_halted=platform_halted,
    )


def make_event(
    *,
    level: KSLevelName = KSLevelName.K5,
    event_type: LevelEventType = (
        LevelEventType.CROSSED_UP
    ),
    timestamp: datetime | None = None,
    trading_date: date = TRADING_DATE,
    level_price: float = 24500.0,
    market_price: float = 24501.0,
) -> LevelEvent:
    event_time = timestamp or datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    return LevelEvent(
        trading_date=trading_date,
        level=level,
        event_type=event_type,
        level_price=level_price,
        market_price=market_price,
        timestamp=event_time,
    )


def test_signal_exactly_at_920_is_allowed() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(
            timestamp=datetime(
                2026,
                8,
                7,
                9,
                20,
                0,
            )
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.accepted is True


def test_signal_one_second_before_920_is_rejected() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(
            timestamp=datetime(
                2026,
                8,
                7,
                9,
                19,
                59,
            )
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.accepted is False
    assert result.reason is SignalEngineReason.NOT_ELIGIBLE
    assert (
        result.eligibility_reason
        is EligibilityReason.BEFORE_TRADING_WINDOW
    )


def test_signal_one_second_before_1515_is_allowed() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(
            timestamp=datetime(
                2026,
                8,
                7,
                15,
                14,
                59,
            )
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.accepted is True


def test_signal_exactly_at_1515_is_rejected() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(
            timestamp=datetime(
                2026,
                8,
                7,
                15,
                15,
                0,
            )
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.accepted is False
    assert (
        result.eligibility_reason
        is EligibilityReason.AFTER_TRADING_WINDOW
    )


def test_exit_and_stop_blocks_signal() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.CALL,
        context=make_context(
            trading_enabled=False,
        ),
    )

    assert result.accepted is False
    assert (
        result.eligibility_reason
        is EligibilityReason.TRADING_DISABLED
    )


def test_platform_halt_blocks_signal() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.PUT,
        context=make_context(
            platform_halted=True,
        ),
    )

    assert result.accepted is False
    assert (
        result.eligibility_reason
        is EligibilityReason.PLATFORM_HALTED
    )


def test_non_monitoring_state_blocks_signal() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.CALL,
        context=make_context(
            session_state=(
                StrategySessionState.LEVELS_READY
            ),
        ),
    )

    assert result.accepted is False
    assert (
        result.eligibility_reason
        is EligibilityReason.STRATEGY_NOT_MONITORING
    )


def test_wrong_trading_date_is_rejected() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(
            trading_date=date(
                2026,
                8,
                8,
            ),
            timestamp=datetime(
                2026,
                8,
                8,
                10,
                0,
            ),
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.accepted is False
    assert (
        result.eligibility_reason
        is EligibilityReason.WRONG_TRADING_DATE
    )


def test_non_entry_level_is_rejected_before_builder() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(
            level=KSLevelName.K3,
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.accepted is False
    assert (
        result.eligibility_reason
        is EligibilityReason.INVALID_LEVEL
    )


def test_duplicate_burst_only_allows_first_signal() -> None:
    engine = make_engine(
        suppression_seconds=5.0
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    results = []

    for offset in (
        0,
        1,
        2,
        3,
        4,
    ):
        result = engine.process(
            event=make_event(
                timestamp=start
                + timedelta(seconds=offset),
            ),
            direction=SignalDirection.CALL,
            context=make_context(),
        )

        results.append(result)

    assert results[0].accepted is True

    for result in results[1:]:
        assert result.accepted is False
        assert (
            result.reason
            is SignalEngineReason.DUPLICATE
        )


def test_duplicate_window_expiry_still_blocked_by_level_lock() -> None:
    engine = make_engine(
        suppression_seconds=1.0
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    first = engine.process(
        event=make_event(
            timestamp=start,
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.accepted is True

    second = engine.process(
        event=make_event(
            timestamp=start
            + timedelta(seconds=10),
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert second.accepted is False
    assert (
        second.reason
        is SignalEngineReason.LEVEL_LOCKED
    )


def test_execution_failure_release_allows_future_signal() -> None:
    engine = make_engine(
        suppression_seconds=1.0
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    first = engine.process(
        event=make_event(
            timestamp=start,
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.signal is not None

    assert engine.release_signal_lock(
        first.signal
    ) is True

    later = engine.process(
        event=make_event(
            timestamp=start
            + timedelta(seconds=5),
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert later.accepted is True


def test_active_trade_blocks_signal_even_after_long_delay() -> None:
    engine = make_engine(
        suppression_seconds=1.0
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    first = engine.process(
        event=make_event(
            timestamp=start,
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.signal is not None

    engine.mark_trade_open(
        first.signal
    )

    later = engine.process(
        event=make_event(
            timestamp=start
            + timedelta(minutes=30),
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert later.accepted is False
    assert (
        later.reason
        is SignalEngineReason.LEVEL_LOCKED
    )


def test_closed_trade_allows_reentry() -> None:
    engine = make_engine(
        suppression_seconds=60.0
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    first = engine.process(
        event=make_event(
            timestamp=start,
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.signal is not None

    engine.mark_trade_open(
        first.signal
    )

    engine.mark_trade_closed(
        level=EntryLevel.K5,
        closed_at=start
        + timedelta(minutes=10),
    )

    second = engine.process(
        event=make_event(
            timestamp=start
            + timedelta(minutes=11),
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert second.accepted is True
    assert second.signal is not None
    assert second.signal.is_reentry is True


def test_other_levels_are_independent() -> None:
    engine = make_engine()

    first = engine.process(
        event=make_event(
            level=KSLevelName.K5,
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    second = engine.process(
        event=make_event(
            level=KSLevelName.K6,
            timestamp=datetime(
                2026,
                8,
                7,
                10,
                0,
                1,
            ),
        ),
        direction=SignalDirection.PUT,
        context=make_context(),
    )

    assert first.accepted is True
    assert second.accepted is True


def test_queue_full_returns_false() -> None:
    queue = SignalQueue(
        max_size=1
    )

    engine = make_engine()

    first = engine.process(
        event=make_event(
            level=KSLevelName.K5,
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    second = engine.process(
        event=make_event(
            level=KSLevelName.K6,
            timestamp=datetime(
                2026,
                8,
                7,
                10,
                0,
                1,
            ),
        ),
        direction=SignalDirection.PUT,
        context=make_context(),
    )

    assert first.signal is not None
    assert second.signal is not None

    assert queue.put(first.signal) is True
    assert queue.put(second.signal) is False


def test_queue_full_signal_can_be_cancelled_in_lifecycle() -> None:
    queue = SignalQueue(
        max_size=1
    )

    lifecycle = SignalLifecycleManager()

    engine = make_engine()

    first = engine.process(
        event=make_event(
            level=KSLevelName.K5,
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    second = engine.process(
        event=make_event(
            level=KSLevelName.K6,
            timestamp=datetime(
                2026,
                8,
                7,
                10,
                0,
                1,
            ),
        ),
        direction=SignalDirection.PUT,
        context=make_context(),
    )

    assert first.signal is not None
    assert second.signal is not None

    lifecycle.register(
        first.signal
    )

    lifecycle.register(
        second.signal
    )

    assert queue.put(
        first.signal
    ) is True

    lifecycle.transition(
        first.signal.signal_id,
        SignalState.QUEUED,
        first.signal.generated_at
        + timedelta(milliseconds=1),
    )

    assert queue.put(
        second.signal
    ) is False

    lifecycle.transition(
        second.signal.signal_id,
        SignalState.CANCELLED,
        second.signal.generated_at
        + timedelta(milliseconds=1),
        reason="signal queue full",
    )

    assert (
        lifecycle.get_state(
            second.signal.signal_id
        )
        is SignalState.CANCELLED
    )


def test_terminal_lifecycle_signal_cannot_transition_again() -> None:
    manager = SignalLifecycleManager()

    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.signal is not None

    signal = result.signal

    manager.register(signal)

    manager.transition(
        signal.signal_id,
        SignalState.REJECTED,
        signal.generated_at
        + timedelta(seconds=1),
        reason="downstream failure",
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


def test_unknown_signal_lookup_fails() -> None:
    manager = SignalLifecycleManager()

    with pytest.raises(
        KeyError,
        match="signal not registered",
    ):
        manager.get_state(
            SignalId("UNKNOWN-SIGNAL")
        )