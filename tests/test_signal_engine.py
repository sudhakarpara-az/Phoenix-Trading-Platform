from datetime import date, datetime, timedelta

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
from src.signals.signal_builder import (
    SignalBuilder,
)
from src.signals.signal_engine import (
    SignalEngine,
    SignalEngineReason,
)
from src.signals.signal_types import (
    SignalDirection,
    SignalReason,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    LevelEvent,
    LevelEventType,
    StrategySessionState,
)


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"


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
    )


def make_context(
    *,
    trading_enabled: bool = True,
    platform_halted: bool = False,
    session_state: StrategySessionState = (
        StrategySessionState.MONITORING
    ),
) -> EligibilityContext:
    return EligibilityContext(
        trading_date=TRADING_DATE,
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
        trading_date=TRADING_DATE,
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        instrument_symbol=INSTRUMENT_SYMBOL,
        level=level,
        event_type=event_type,
        level_price=24500.0,
        market_price=24501.0,
        timestamp=event_time,
    )


def test_valid_event_creates_signal() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.accepted is True
    assert result.reason is SignalEngineReason.CREATED
    assert result.signal is not None
    assert result.signal.level is EntryLevel.K5
    assert result.signal.direction is SignalDirection.CALL


def test_signal_preserves_strategy_instrument_identity() -> None:
    engine = make_engine()

    event = LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id="54321",
        instrument_symbol="NIFTY-24550-PE",
        level=KSLevelName.K5,
        event_type=LevelEventType.CROSSED_DOWN,
        level_price=24500.0,
        market_price=24499.0,
        timestamp=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
    )

    result = engine.process(
        event=event,
        direction=SignalDirection.PUT,
        context=make_context(),
    )

    assert result.accepted is True
    assert result.signal is not None

    assert (
        result.signal.instrument_security_id
        == event.instrument_security_id
    )

    assert (
        result.signal.instrument_symbol
        == event.instrument_symbol
    )


def test_put_direction_is_preserved() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.PUT,
        context=make_context(),
    )

    assert result.signal is not None
    assert result.signal.direction is SignalDirection.PUT


def test_disabled_trading_is_rejected() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.CALL,
        context=make_context(
            trading_enabled=False
        ),
    )

    assert result.accepted is False
    assert result.reason is SignalEngineReason.NOT_ELIGIBLE

    assert (
        result.eligibility_reason
        is EligibilityReason.TRADING_DISABLED
    )


def test_halted_platform_is_rejected() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.CALL,
        context=make_context(
            platform_halted=True
        ),
    )

    assert result.accepted is False

    assert (
        result.eligibility_reason
        is EligibilityReason.PLATFORM_HALTED
    )


def test_duplicate_event_is_rejected() -> None:
    engine = make_engine(
        suppression_seconds=5
    )

    timestamp = datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    first = engine.process(
        event=make_event(
            timestamp=timestamp
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    second = engine.process(
        event=make_event(
            timestamp=timestamp
            + timedelta(seconds=1)
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.accepted is True

    assert second.accepted is False
    assert second.reason is SignalEngineReason.DUPLICATE


def test_level_lock_blocks_later_event() -> None:
    engine = make_engine(
        suppression_seconds=1
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
            timestamp=start
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.accepted is True

    second = engine.process(
        event=make_event(
            timestamp=start
            + timedelta(seconds=10)
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert second.accepted is False

    assert (
        second.reason
        is SignalEngineReason.LEVEL_LOCKED
    )


def test_different_levels_can_generate_signals() -> None:
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
        ),
        direction=SignalDirection.PUT,
        context=make_context(),
    )

    assert first.accepted is True
    assert second.accepted is True

    assert first.signal is not None
    assert second.signal is not None

    assert first.signal.level is EntryLevel.K5
    assert second.signal.level is EntryLevel.K6


def test_mark_trade_open_activates_reentry_state() -> None:
    engine = make_engine()

    result = engine.process(
        event=make_event(),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.signal is not None

    engine.mark_trade_open(
        result.signal
    )


def test_trade_close_allows_reentry() -> None:
    engine = make_engine(
        suppression_seconds=30
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
            timestamp=start
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.accepted is True
    assert first.signal is not None

    engine.mark_trade_open(
        first.signal
    )

    engine.mark_trade_closed(
        instrument_security_id=(
            first.signal.instrument_security_id
        ),
        level=EntryLevel.K5,
        closed_at=start
        + timedelta(minutes=15),
    )

    second = engine.process(
        event=make_event(
            timestamp=start
            + timedelta(minutes=20),
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert second.accepted is True
    assert second.signal is not None

    assert second.signal.is_reentry is True

    assert (
        second.signal.reason
        is SignalReason.REENTRY
    )


def test_signal_lock_can_be_released_if_execution_never_starts() -> None:
    engine = make_engine(
        suppression_seconds=1
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    result = engine.process(
        event=make_event(
            timestamp=start
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert result.signal is not None

    released = engine.release_signal_lock(
        result.signal
    )

    assert released is True

    next_result = engine.process(
        event=make_event(
            timestamp=start
            + timedelta(seconds=5),
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert next_result.accepted is True

def test_same_level_on_different_contracts_can_generate_signals_independently() -> None:
    engine = make_engine(
        suppression_seconds=30
    )

    timestamp = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    call_event = LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id="12345",
        instrument_symbol="NIFTY-24550-CE",
        level=KSLevelName.K5,
        event_type=LevelEventType.CROSSED_UP,
        level_price=100.0,
        market_price=101.0,
        timestamp=timestamp,
    )

    put_event = LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id="67890",
        instrument_symbol="NIFTY-24550-PE",
        level=KSLevelName.K5,
        event_type=LevelEventType.CROSSED_UP,
        level_price=100.0,
        market_price=101.0,
        timestamp=timestamp,
    )

    first = engine.process(
        event=call_event,
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.accepted is True
    assert first.signal is not None

    engine.mark_trade_open(
        first.signal
    )

    second = engine.process(
        event=put_event,
        direction=SignalDirection.PUT,
        context=make_context(),
    )

    assert second.accepted is True
    assert second.reason is SignalEngineReason.CREATED
    assert second.signal is not None

    assert (
        second.signal.instrument_security_id
        == "67890"
    )

    assert second.signal.level is EntryLevel.K5
    assert second.signal.is_reentry is False



def test_released_signal_preserves_duplicate_suppression_window() -> None:
    engine = make_engine(
        suppression_seconds=5
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    first = engine.process(
        event=make_event(
            timestamp=start
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert first.accepted is True
    assert first.signal is not None

    assert (
        engine.release_signal_lock(
            first.signal
        )
        is True
    )

    immediate_retry = engine.process(
        event=make_event(
            timestamp=(
                start
                + timedelta(seconds=1)
            )
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert immediate_retry.accepted is False

    assert (
        immediate_retry.reason
        is SignalEngineReason.DUPLICATE
    )

    after_window = engine.process(
        event=make_event(
            timestamp=(
                start
                + timedelta(seconds=5)
            )
        ),
        direction=SignalDirection.CALL,
        context=make_context(),
    )

    assert after_window.accepted is True
    assert after_window.signal is not None
    assert after_window.signal.is_reentry is False
