"""
M03 KS Phoenix Strategy integration tests.

Validates the complete broker-independent strategy pipeline:

MarketTick
    -> TradingSessionManager
    -> ReferenceCandleBuilder
    -> DailyKSLevelService
    -> KSLevels
    -> LevelMonitor
    -> LevelEvent

No Dhan connection, option selection, signals,
or order execution are involved.
"""

from datetime import date, datetime

import pytest

from src.market.market_types import (
    Exchange,
    MarketTick,
)
from src.strategy.daily_ks_level_service import (
    DailyKSLevelService,
)
from src.strategy.level_monitor import LevelMonitor
from src.strategy.reference_candle_builder import (
    ReferenceCandleBuilder,
)
from src.strategy.strategy_types import (
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
    Create one synthetic NIFTY underlying tick.
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


def build_strategy_pipeline():
    """
    Construct the complete M03 strategy pipeline.
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

    return (
        session,
        candle_builder,
        level_service,
        level_monitor,
    )


def build_reference_candle(
    session: TradingSessionManager,
    candle_builder: ReferenceCandleBuilder,
):
    """
    Simulate the NIFTY 09:15–09:20 reference period.
    """

    # 09:15
    assert (
        session.update(
            datetime(2026, 8, 7, 9, 15)
        )
        is StrategySessionState.BUILDING_REFERENCE_CANDLE
    )

    ticks = [
        make_tick(24500.0, 9, 15, 0),
        make_tick(24510.0, 9, 15, 30),
        make_tick(24520.0, 9, 16, 0),
        make_tick(24530.0, 9, 17, 0),
        make_tick(24490.0, 9, 18, 0),
        make_tick(24480.0, 9, 19, 0),
        make_tick(24510.0, 9, 19, 59),
    ]

    for market_tick in ticks:
        accepted = candle_builder.process_tick(
            market_tick
        )

        assert accepted is True

    # At exactly 09:20 the building period is over.
    assert (
        session.update(
            datetime(2026, 8, 7, 9, 20)
        )
        is StrategySessionState.LEVELS_READY
    )

    candle = candle_builder.finalize(
        datetime(2026, 8, 7, 9, 20)
    )

    return candle


def test_complete_reference_candle_pipeline() -> None:
    (
        session,
        candle_builder,
        _,
        _,
    ) = build_strategy_pipeline()

    candle = build_reference_candle(
        session,
        candle_builder,
    )

    assert candle.trading_date == TRADING_DATE

    assert candle.open == 24500.0
    assert candle.high == 24530.0
    assert candle.low == 24480.0
    assert candle.close == 24510.0

    assert candle_builder.tick_count == 7
    assert candle_builder.is_finalized is True


def test_complete_ks_calculation_pipeline() -> None:
    (
        session,
        candle_builder,
        level_service,
        _,
    ) = build_strategy_pipeline()

    candle = build_reference_candle(
        session,
        candle_builder,
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

    # Base Pine values
    assert levels.n1 == pytest.approx(24555.0)
    assert levels.n2 == pytest.approx(24505.0)
    assert levels.c1 == pytest.approx(24530.0)

    assert levels.e_level == pytest.approx(24427.0)
    assert levels.t_level == pytest.approx(24678.0)

    # Final KS values
    assert levels.k0 == pytest.approx(38600.46)
    assert levels.k1 == pytest.approx(5783.18)

    assert levels.k2 == pytest.approx(
        30822.76464
    )

    assert levels.k3 == pytest.approx(
        26064.25904
    )

    assert levels.k5 == pytest.approx(
        22191.82
    )

    assert levels.k6 == pytest.approx(
        18319.38096
    )

    assert levels.k7 == pytest.approx(
        13002.9816
    )


def test_strategy_moves_to_monitoring_after_levels_ready() -> None:
    (
        session,
        candle_builder,
        level_service,
        _,
    ) = build_strategy_pipeline()

    candle = build_reference_candle(
        session,
        candle_builder,
    )

    level_service.calculate(candle)

    assert level_service.is_ready is True

    session.mark_levels_ready()

    assert (
        session.state()
        is StrategySessionState.MONITORING
    )

    assert (
        session.can_monitor_levels(
            datetime(2026, 8, 7, 9, 21)
        )
        is True
    )


def test_live_price_crosses_k5() -> None:
    (
        session,
        candle_builder,
        level_service,
        monitor,
    ) = build_strategy_pipeline()

    candle = build_reference_candle(
        session,
        candle_builder,
    )

    levels = level_service.calculate(candle)

    session.mark_levels_ready()

    assert (
        session.state()
        is StrategySessionState.MONITORING
    )

    # Establish previous price below K5.
    events = monitor.process_tick(
        make_tick(
            levels.k5 - 5.0,
            10,
            0,
            0,
        )
    )

    assert events == ()

    # Cross upward through K5.
    events = monitor.process_tick(
        make_tick(
            levels.k5 + 1.0,
            10,
            0,
            1,
        )
    )

    k5_events = [
        event
        for event in events
        if event.level is KSLevelName.K5
    ]

    assert len(k5_events) == 1

    event = k5_events[0]

    assert (
        event.event_type
        is LevelEventType.CROSSED_UP
    )

    assert event.level_price == pytest.approx(
        levels.k5
    )


def test_live_price_crosses_k6() -> None:
    (
        session,
        candle_builder,
        level_service,
        monitor,
    ) = build_strategy_pipeline()

    candle = build_reference_candle(
        session,
        candle_builder,
    )

    levels = level_service.calculate(candle)

    session.mark_levels_ready()

    monitor.process_tick(
        make_tick(
            levels.k6 - 5.0,
            10,
            1,
            0,
        )
    )

    events = monitor.process_tick(
        make_tick(
            levels.k6 + 1.0,
            10,
            1,
            1,
        )
    )

    matching = [
        event
        for event in events
        if event.level is KSLevelName.K6
    ]

    assert len(matching) == 1

    assert (
        matching[0].event_type
        is LevelEventType.CROSSED_UP
    )


def test_live_price_crosses_k7() -> None:
    (
        session,
        candle_builder,
        level_service,
        monitor,
    ) = build_strategy_pipeline()

    candle = build_reference_candle(
        session,
        candle_builder,
    )

    levels = level_service.calculate(candle)

    session.mark_levels_ready()

    monitor.process_tick(
        make_tick(
            levels.k7 + 5.0,
            10,
            2,
            0,
        )
    )

    events = monitor.process_tick(
        make_tick(
            levels.k7 - 1.0,
            10,
            2,
            1,
        )
    )

    matching = [
        event
        for event in events
        if event.level is KSLevelName.K7
    ]

    assert len(matching) == 1

    assert (
        matching[0].event_type
        is LevelEventType.CROSSED_DOWN
    )


def test_no_level_monitoring_before_levels_exist() -> None:
    (
        _,
        _,
        _,
        monitor,
    ) = build_strategy_pipeline()

    events = monitor.process_tick(
        make_tick(
            24500.0,
            9,
            18,
        )
    )

    assert events == ()


def test_force_exit_closes_strategy_session() -> None:
    (
        session,
        candle_builder,
        level_service,
        _,
    ) = build_strategy_pipeline()

    candle = build_reference_candle(
        session,
        candle_builder,
    )

    level_service.calculate(candle)

    session.mark_levels_ready()

    assert (
        session.state()
        is StrategySessionState.MONITORING
    )

    state = session.update(
        datetime(
            2026,
            8,
            7,
            15,
            15,
        )
    )

    assert state is StrategySessionState.CLOSED


def test_daily_services_can_reset_for_next_session() -> None:
    (
        session,
        candle_builder,
        level_service,
        monitor,
    ) = build_strategy_pipeline()

    candle = build_reference_candle(
        session,
        candle_builder,
    )

    level_service.calculate(candle)

    session.mark_levels_ready()

    monitor.process_tick(
        make_tick(
            25000.0,
            10,
            0,
        )
    )

    assert level_service.is_ready is True
    assert candle_builder.is_finalized is True
    assert monitor.previous_price is not None

    # End-of-day / next-session reset.
    candle_builder.reset()
    level_service.reset()
    monitor.reset()

    session.reset_for_day(
        date(2026, 8, 8)
    )

    assert candle_builder.is_finalized is False
    assert candle_builder.tick_count == 0

    assert level_service.is_ready is False
    assert level_service.get_levels() is None

    assert monitor.previous_price is None

    assert (
        session.state()
        is StrategySessionState.WAITING_FOR_MARKET
    )

    assert (
        session.trading_date
        == date(2026, 8, 8)
    )