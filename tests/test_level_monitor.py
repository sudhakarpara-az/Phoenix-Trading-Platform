from datetime import date, datetime

from src.market.market_types import (
    Exchange,
    MarketTick,
)
from src.strategy.daily_ks_level_service import (
    DailyKSLevelService,
)
from src.strategy.level_monitor import LevelMonitor
from src.strategy.strategy_types import (
    EntryLevel,
    LevelEventType,
    ReferenceCandle,
)


TRADING_DATE = date(2026, 8, 7)


def make_service() -> DailyKSLevelService:
    candle = ReferenceCandle(
        trading_date=TRADING_DATE,
        start_time=datetime(2026, 8, 7, 9, 15),
        end_time=datetime(2026, 8, 7, 9, 20),
        open=24500.0,
        high=24530.0,
        low=24480.0,
        close=24510.0,
    )

    service = DailyKSLevelService()

    service.calculate(
        candle,
        calculated_at=datetime(
            2026,
            8,
            7,
            9,
            20,
        ),
    )

    return service


def make_tick(
    price: float,
    hour: int = 10,
    minute: int = 0,
    second: int = 0,
    security_id: str = "13",
    day: int = 7,
) -> MarketTick:
    return MarketTick(
        exchange=Exchange.IDX,
        symbol="NIFTY 50",
        security_id=security_id,
        ltp=price,
        volume=0,
        timestamp=datetime(
            2026,
            8,
            day,
            hour,
            minute,
            second,
        ),
    )


def test_monitor_ignores_tick_when_levels_not_ready() -> None:
    service = DailyKSLevelService()
    monitor = LevelMonitor(service)

    events = monitor.process_tick(
        make_tick(24500.0)
    )

    assert events == ()


def test_monitor_ignores_wrong_security_id() -> None:
    service = make_service()
    monitor = LevelMonitor(service)

    events = monitor.process_tick(
        make_tick(
            price=24500.0,
            security_id="999999",
        )
    )

    assert events == ()


def test_first_tick_on_k5_generates_touch() -> None:
    service = make_service()
    levels = service.require_levels()

    monitor = LevelMonitor(service)

    events = monitor.process_tick(
        make_tick(levels.k5)
    )

    assert len(events) == 1

    event = events[0]

    assert event.level.value == EntryLevel.K5.value
    assert event.event_type is LevelEventType.TOUCHED
    assert event.level_price == levels.k5


def test_cross_up_through_k5() -> None:
    service = make_service()
    levels = service.require_levels()

    monitor = LevelMonitor(service)

    monitor.process_tick(
        make_tick(
            levels.k5 - 10.0,
            second=1,
        )
    )

    events = monitor.process_tick(
        make_tick(
            levels.k5 + 1.0,
            second=2,
        )
    )

    assert len(events) == 1
    assert events[0].event_type is LevelEventType.CROSSED_UP
    assert events[0].level.value == "K5"


def test_cross_down_through_k5() -> None:
    service = make_service()
    levels = service.require_levels()

    monitor = LevelMonitor(service)

    monitor.process_tick(
        make_tick(
            levels.k5 + 10.0,
            second=1,
        )
    )

    events = monitor.process_tick(
        make_tick(
            levels.k5 - 1.0,
            second=2,
        )
    )

    assert len(events) == 1
    assert events[0].event_type is LevelEventType.CROSSED_DOWN
    assert events[0].level.value == "K5"


def test_cross_up_through_k6() -> None:
    service = make_service()
    levels = service.require_levels()

    monitor = LevelMonitor(service)

    monitor.process_tick(
        make_tick(
            levels.k6 - 5.0,
            second=1,
        )
    )

    events = monitor.process_tick(
        make_tick(
            levels.k6 + 0.5,
            second=2,
        )
    )

    matching = [
        event
        for event in events
        if event.level.value == "K6"
    ]

    assert len(matching) == 1
    assert (
        matching[0].event_type
        is LevelEventType.CROSSED_UP
    )


def test_cross_down_through_k7() -> None:
    service = make_service()
    levels = service.require_levels()

    monitor = LevelMonitor(service)

    monitor.process_tick(
        make_tick(
            levels.k7 + 5.0,
            second=1,
        )
    )

    events = monitor.process_tick(
        make_tick(
            levels.k7 - 0.5,
            second=2,
        )
    )

    matching = [
        event
        for event in events
        if event.level.value == "K7"
    ]

    assert len(matching) == 1
    assert (
        matching[0].event_type
        is LevelEventType.CROSSED_DOWN
    )


def test_no_event_when_price_does_not_reach_level() -> None:
    service = make_service()
    levels = service.require_levels()

    monitor = LevelMonitor(service)

    far_above = max(
        levels.k5,
        levels.k6,
        levels.k7,
    ) + 1000.0

    monitor.process_tick(
        make_tick(
            far_above,
            second=1,
        )
    )

    events = monitor.process_tick(
        make_tick(
            far_above + 1.0,
            second=2,
        )
    )

    assert events == ()


def test_touch_tolerance() -> None:
    service = make_service()
    levels = service.require_levels()

    monitor = LevelMonitor(
        service,
        touch_tolerance=0.5,
    )

    events = monitor.process_tick(
        make_tick(
            levels.k5 + 0.4,
        )
    )

    matching = [
        event
        for event in events
        if event.level.value == "K5"
    ]

    assert len(matching) == 1
    assert matching[0].event_type is LevelEventType.TOUCHED


def test_negative_tolerance_is_rejected() -> None:
    service = make_service()

    try:
        LevelMonitor(
            service,
            touch_tolerance=-1.0,
        )

        assert False, "Expected ValueError"

    except ValueError as exc:
        assert (
            str(exc)
            == "touch_tolerance cannot be negative"
        )


def test_monitor_ignores_different_trading_date() -> None:
    service = make_service()
    monitor = LevelMonitor(service)

    events = monitor.process_tick(
        make_tick(
            price=24500.0,
            day=8,
        )
    )

    assert events == ()


def test_previous_price_is_updated() -> None:
    service = make_service()
    monitor = LevelMonitor(service)

    monitor.process_tick(
        make_tick(
            price=25000.0,
        )
    )

    assert monitor.previous_price == 25000.0


def test_reset_clears_monitor_state() -> None:
    service = make_service()
    monitor = LevelMonitor(service)

    monitor.process_tick(
        make_tick(
            price=25000.0,
        )
    )

    monitor.reset()

    assert monitor.previous_price is None
    assert monitor.trading_date is None