"""
M03 -> M04 integration tests.

Validates the complete Phoenix strategy-to-signal pipeline:

Synthetic NIFTY MarketTick
    -> ReferenceCandleBuilder
    -> DailyKSLevelService
    -> LevelMonitor
    -> LevelEvent
    -> SignalEngine
    -> TradingSignal
    -> SignalQueue
    -> SignalLifecycleManager

No option-chain lookup or broker execution occurs here.
"""

from datetime import date, datetime, timedelta

import pytest

from src.market.market_types import (
    Exchange,
    MarketTick,
)

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
    SignalReason,
    SignalState,
)

from src.strategy.daily_ks_level_service import (
    DailyKSLevelService,
)
from src.strategy.level_monitor import LevelMonitor
from src.strategy.reference_candle_builder import (
    ReferenceCandleBuilder,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    LevelEventType,
    StrategySessionState,
)
from src.strategy.trading_session_manager import (
    TradingSessionManager,
)


TRADING_DATE = date(2026, 8, 7)


def make_tick(
    price: float,
    hour: int,
    minute: int,
    second: int = 0,
) -> MarketTick:
    """
    Create one synthetic NIFTY underlying MarketTick.
    """

    return MarketTick(
        exchange=Exchange.IDX,
        symbol="NIFTY 50",
        security_id="13",
        ltp=price,
        volume=0,
        timestamp=datetime(
            2026,
            8,
            7,
            hour,
            minute,
            second,
        ),
    )


def build_pipeline():
    """
    Construct complete M03 + M04 pipeline.
    """

    session = TradingSessionManager()

    candle_builder = ReferenceCandleBuilder(
        security_id="13",
    )

    level_service = DailyKSLevelService()

    level_monitor = LevelMonitor(
        level_service=level_service,
        security_id="13",
    )

    duplicate_guard = DuplicateSignalGuard(
        suppression_seconds=5.0,
    )

    level_locks = LevelLockManager()

    reentry_manager = ReentryStateManager()

    signal_engine = SignalEngine(
        eligibility_policy=SignalEligibilityPolicy(),
        duplicate_guard=duplicate_guard,
        level_lock_manager=level_locks,
        reentry_manager=reentry_manager,
        signal_builder=SignalBuilder(),
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
    )

    signal_queue = SignalQueue(
        max_size=100,
    )

    lifecycle = SignalLifecycleManager()

    return {
        "session": session,
        "candle_builder": candle_builder,
        "level_service": level_service,
        "level_monitor": level_monitor,
        "signal_engine": signal_engine,
        "signal_queue": signal_queue,
        "lifecycle": lifecycle,
        "level_locks": level_locks,
        "reentry_manager": reentry_manager,
    }


def prepare_trading_day(pipeline):
    """
    Build the 09:15-09:20 reference candle,
    calculate KS levels, and move the strategy
    into MONITORING state.
    """

    session = pipeline["session"]
    candle_builder = pipeline["candle_builder"]
    level_service = pipeline["level_service"]

    assert (
        session.update(
            datetime(2026, 8, 7, 9, 15)
        )
        is StrategySessionState.BUILDING_REFERENCE_CANDLE
    )

    reference_ticks = [
        make_tick(24500.0, 9, 15, 0),
        make_tick(24510.0, 9, 15, 30),
        make_tick(24520.0, 9, 16, 0),
        make_tick(24530.0, 9, 17, 0),
        make_tick(24490.0, 9, 18, 0),
        make_tick(24480.0, 9, 19, 0),
        make_tick(24510.0, 9, 19, 59),
    ]

    for tick in reference_ticks:
        assert candle_builder.process_tick(tick) is True

    assert (
        session.update(
            datetime(2026, 8, 7, 9, 20)
        )
        is StrategySessionState.LEVELS_READY
    )

    candle = candle_builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    levels = level_service.calculate(
        candle,
        calculated_at=datetime(
            2026,
            8,
            7,
            9,
            20,
            1,
        ),
    )

    session.mark_levels_ready()

    assert (
        session.state()
        is StrategySessionState.MONITORING
    )

    return levels


def monitoring_context(
    pipeline,
    *,
    trading_enabled: bool = True,
    platform_halted: bool = False,
) -> EligibilityContext:
    return EligibilityContext(
        trading_date=TRADING_DATE,
        session_state=pipeline["session"].state(),
        trading_enabled=trading_enabled,
        platform_halted=platform_halted,
    )


def get_level_event(
    events,
    level: KSLevelName,
):
    matches = [
        event
        for event in events
        if event.level is level
    ]

    assert len(matches) == 1

    return matches[0]


def test_k5_cross_generates_trading_signal() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]

    # Establish price below K5.
    assert monitor.process_tick(
        make_tick(
            levels.k5 - 5.0,
            10,
            0,
            0,
        )
    ) == ()

    # Cross upward through K5.
    events = monitor.process_tick(
        make_tick(
            levels.k5 + 1.0,
            10,
            0,
            1,
        )
    )

    event = get_level_event(
        events,
        KSLevelName.K5,
    )

    assert (
        event.event_type
        is LevelEventType.CROSSED_UP
    )

    result = engine.process(
        event=event,
        direction=SignalDirection.CALL,
        context=monitoring_context(pipeline),
    )

    assert result.accepted is True
    assert result.reason is SignalEngineReason.CREATED
    assert result.signal is not None

    signal = result.signal

    assert signal.level is EntryLevel.K5
    assert signal.direction is SignalDirection.CALL
    assert signal.is_reentry is False
    assert signal.reason is SignalReason.CROSS_UP


def test_generated_signal_enters_queue() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]
    queue = pipeline["signal_queue"]

    monitor.process_tick(
        make_tick(
            levels.k5 - 5.0,
            10,
            0,
            0,
        )
    )

    events = monitor.process_tick(
        make_tick(
            levels.k5 + 1.0,
            10,
            0,
            1,
        )
    )

    event = get_level_event(
        events,
        KSLevelName.K5,
    )

    result = engine.process(
        event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert result.signal is not None

    assert queue.put(
        result.signal
    ) is True

    assert queue.size() == 1
    assert queue.peek() is result.signal


def test_signal_lifecycle_reaches_queued_state() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]
    queue = pipeline["signal_queue"]
    lifecycle = pipeline["lifecycle"]

    monitor.process_tick(
        make_tick(
            levels.k5 - 5.0,
            10,
            0,
            0,
        )
    )

    events = monitor.process_tick(
        make_tick(
            levels.k5 + 1.0,
            10,
            0,
            1,
        )
    )

    event = get_level_event(
        events,
        KSLevelName.K5,
    )

    result = engine.process(
        event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert result.signal is not None

    signal = result.signal

    lifecycle.register(signal)

    assert (
        lifecycle.get_state(
            signal.signal_id
        )
        is SignalState.CREATED
    )

    assert queue.put(signal) is True

    lifecycle.transition(
        signal_id=signal.signal_id,
        to_state=SignalState.QUEUED,
        changed_at=signal.generated_at
        + timedelta(milliseconds=1),
    )

    assert (
        lifecycle.get_state(
            signal.signal_id
        )
        is SignalState.QUEUED
    )


def test_complete_signal_consumption_lifecycle() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]
    queue = pipeline["signal_queue"]
    lifecycle = pipeline["lifecycle"]

    monitor.process_tick(
        make_tick(
            levels.k5 - 5.0,
            10,
            0,
            0,
        )
    )

    event = get_level_event(
        monitor.process_tick(
            make_tick(
                levels.k5 + 1.0,
                10,
                0,
                1,
            )
        ),
        KSLevelName.K5,
    )

    result = engine.process(
        event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert result.signal is not None

    signal = result.signal

    lifecycle.register(signal)

    assert queue.put(signal) is True

    lifecycle.transition(
        signal.signal_id,
        SignalState.QUEUED,
        signal.generated_at
        + timedelta(milliseconds=1),
    )

    consumed_signal = queue.get()

    assert consumed_signal is signal

    lifecycle.transition(
        signal.signal_id,
        SignalState.ACCEPTED,
        signal.generated_at
        + timedelta(milliseconds=2),
    )

    lifecycle.transition(
        signal.signal_id,
        SignalState.CONSUMED,
        signal.generated_at
        + timedelta(milliseconds=3),
    )

    assert (
        lifecycle.get_state(signal.signal_id)
        is SignalState.CONSUMED
    )

    assert lifecycle.is_terminal(
        signal.signal_id
    ) is True


def test_duplicate_k5_event_does_not_create_second_signal() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    first_event = get_level_event(
        (
            monitor.process_tick(
                make_tick(
                    levels.k5 - 5.0,
                    10,
                    0,
                    0,
                )
            )
            or monitor.process_tick(
                make_tick(
                    levels.k5 + 1.0,
                    10,
                    0,
                    1,
                )
            )
        ),
        KSLevelName.K5,
    )

    first_result = engine.process(
        first_event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert first_result.accepted is True

    # Directly submit a duplicate LevelEvent candidate
    # within the suppression window.
    duplicate_event = type(first_event)(
        trading_date=first_event.trading_date,
        level=first_event.level,
        event_type=first_event.event_type,
        level_price=first_event.level_price,
        market_price=first_event.market_price,
        timestamp=start
        + timedelta(seconds=2),
    )

    duplicate_result = engine.process(
        duplicate_event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert duplicate_result.accepted is False

    assert (
        duplicate_result.reason
        is SignalEngineReason.DUPLICATE
    )


def test_active_k5_lock_blocks_new_signal() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]

    monitor.process_tick(
        make_tick(
            levels.k5 - 5,
            10,
            0,
            0,
        )
    )

    event = get_level_event(
        monitor.process_tick(
            make_tick(
                levels.k5 + 1,
                10,
                0,
                1,
            )
        ),
        KSLevelName.K5,
    )

    first = engine.process(
        event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert first.accepted is True
    assert first.signal is not None

    engine.mark_trade_open(
        first.signal
    )

    later_event = type(event)(
        trading_date=event.trading_date,
        level=event.level,
        event_type=event.event_type,
        level_price=event.level_price,
        market_price=event.market_price,
        timestamp=event.timestamp
        + timedelta(seconds=10),
    )

    second = engine.process(
        later_event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert second.accepted is False

    assert (
        second.reason
        is SignalEngineReason.LEVEL_LOCKED
    )


def test_closed_k5_trade_allows_reentry_signal() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    monitor.process_tick(
        make_tick(
            levels.k5 - 5,
            10,
            0,
            0,
        )
    )

    first_event = get_level_event(
        monitor.process_tick(
            make_tick(
                levels.k5 + 1,
                10,
                0,
                1,
            )
        ),
        KSLevelName.K5,
    )

    first = engine.process(
        first_event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert first.signal is not None

    engine.mark_trade_open(
        first.signal
    )

    engine.mark_trade_closed(
        level=EntryLevel.K5,
        closed_at=start
        + timedelta(minutes=20),
    )

    reentry_event = type(first_event)(
        trading_date=TRADING_DATE,
        level=KSLevelName.K5,
        event_type=LevelEventType.CROSSED_UP,
        level_price=levels.k5,
        market_price=levels.k5 + 1,
        timestamp=start
        + timedelta(minutes=30),
    )

    second = engine.process(
        reentry_event,
        SignalDirection.CALL,
        monitoring_context(pipeline),
    )

    assert second.accepted is True
    assert second.signal is not None

    assert second.signal.is_reentry is True

    assert (
        second.signal.reason
        is SignalReason.REENTRY
    )


def test_exit_and_stop_blocks_new_signal() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]

    monitor.process_tick(
        make_tick(
            levels.k6 - 5,
            11,
            0,
            0,
        )
    )

    event = get_level_event(
        monitor.process_tick(
            make_tick(
                levels.k6 + 1,
                11,
                0,
                1,
            )
        ),
        KSLevelName.K6,
    )

    result = engine.process(
        event,
        SignalDirection.CALL,
        monitoring_context(
            pipeline,
            trading_enabled=False,
        ),
    )

    assert result.accepted is False

    assert (
        result.reason
        is SignalEngineReason.NOT_ELIGIBLE
    )

    assert (
        result.eligibility_reason
        is EligibilityReason.TRADING_DISABLED
    )


def test_platform_halt_blocks_new_signal() -> None:
    pipeline = build_pipeline()

    levels = prepare_trading_day(
        pipeline
    )

    monitor = pipeline["level_monitor"]
    engine = pipeline["signal_engine"]

    monitor.process_tick(
        make_tick(
            levels.k7 - 5,
            12,
            0,
            0,
        )
    )

    event = get_level_event(
        monitor.process_tick(
            make_tick(
                levels.k7 + 1,
                12,
                0,
                1,
            )
        ),
        KSLevelName.K7,
    )

    result = engine.process(
        event,
        SignalDirection.PUT,
        monitoring_context(
            pipeline,
            platform_halted=True,
        ),
    )

    assert result.accepted is False

    assert (
        result.eligibility_reason
        is EligibilityReason.PLATFORM_HALTED
    )