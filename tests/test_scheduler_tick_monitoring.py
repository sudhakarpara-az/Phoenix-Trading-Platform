"""
M10-T09 selected CE/PE live-tick monitoring orchestration.
"""

from datetime import date, datetime

import pytest

from src.market.market_types import (
    Exchange,
    MarketTick,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.services.scheduler import (
    TradingDayLevelPreparationResult,
    TradingDayMonitoringCoordinator,
    TradingDayScheduler,
    TradingDayState,
    TradingDayTickMonitoringCoordinator,
    TradingDayTickMonitoringError,
)
from src.strategy.daily_ks_level_service import (
    DailyKSLevelService,
)
from src.strategy.strategy_types import (
    LevelEventType,
    ReferenceCandle,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)

EXPIRY = date(
    2026,
    8,
    13,
)

CALL_SECURITY_ID = "41009"
CALL_SYMBOL = "NIFTY-24500-CE"

PUT_SECURITY_ID = "41019"
PUT_SYMBOL = "NIFTY-24500-PE"


def dt(
    hour: int,
    minute: int,
    second: int = 0,
    *,
    day: int = 10,
) -> datetime:
    return datetime(
        2026,
        8,
        day,
        hour,
        minute,
        second,
    )


def make_selected_option(
    *,
    option_type: OptionType,
    security_id: str,
    symbol: str,
    strike: float = 24500.0,
) -> SelectedOption:
    delta = (
        0.60
        if option_type is OptionType.CALL
        else -0.60
    )

    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY",
                symbol=symbol,
                security_id=security_id,
                option_type=option_type,
                strike=strike,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=200.0,
                received_at=dt(
                    9,
                    16,
                ),
            ),
            greeks=OptionGreeks(
                delta=delta,
                calculated_at=dt(
                    9,
                    16,
                ),
            ),
        ),
        selected_at=dt(
            9,
            16,
        ),
        selection_delta_target=0.60,
    )


def make_level_service(
    *,
    security_id: str,
    symbol: str,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> tuple[
    DailyKSLevelService,
    ReferenceCandle,
]:
    candle = ReferenceCandle(
        trading_date=TRADING_DATE,
        instrument_security_id=security_id,
        instrument_symbol=symbol,
        start_time=dt(
            9,
            15,
        ),
        end_time=dt(
            9,
            16,
        ),
        open=open_price,
        high=high,
        low=low,
        close=close,
    )

    service = DailyKSLevelService()

    service.calculate(
        candle=candle,
        calculated_at=dt(
            9,
            17,
        ),
    )

    return service, candle


def make_preparation():
    selected_call = make_selected_option(
        option_type=OptionType.CALL,
        security_id=CALL_SECURITY_ID,
        symbol=CALL_SYMBOL,
    )

    selected_put = make_selected_option(
        option_type=OptionType.PUT,
        security_id=PUT_SECURITY_ID,
        symbol=PUT_SYMBOL,
    )

    call_service, call_candle = (
        make_level_service(
            security_id=CALL_SECURITY_ID,
            symbol=CALL_SYMBOL,
            open_price=100.0,
            high=120.0,
            low=80.0,
            close=110.0,
        )
    )

    put_service, put_candle = (
        make_level_service(
            security_id=PUT_SECURITY_ID,
            symbol=PUT_SYMBOL,
            open_price=150.0,
            high=180.0,
            low=130.0,
            close=160.0,
        )
    )

    preparation = (
        TradingDayLevelPreparationResult(
            selected_call=selected_call,
            selected_put=selected_put,
            call_reference_candle=call_candle,
            put_reference_candle=put_candle,
            call_levels=(
                call_service.require_levels()
            ),
            put_levels=(
                put_service.require_levels()
            ),
            prepared_at=dt(
                9,
                17,
            ),
        )
    )

    return (
        preparation,
        call_service,
        put_service,
    )


def make_waiting_scheduler() -> TradingDayScheduler:
    scheduler = TradingDayScheduler(
        trading_date=TRADING_DATE,
        created_at=dt(
            8,
            30,
        ),
    )

    scheduler.start(
        started_at=dt(
            9,
            0,
        )
    )

    transitions = (
        (
            TradingDayState.WAITING_FOR_REFERENCE_CLOSE,
            dt(
                9,
                15,
            ),
        ),
        (
            TradingDayState.SELECTING_OPTIONS,
            dt(
                9,
                16,
            ),
        ),
        (
            TradingDayState.PREPARING_LEVELS,
            dt(
                9,
                16,
                1,
            ),
        ),
        (
            TradingDayState.WAITING_FOR_MONITORING,
            dt(
                9,
                17,
            ),
        ),
    )

    for state, transitioned_at in transitions:
        scheduler.transition(
            target_state=state,
            transitioned_at=transitioned_at,
        )

    return scheduler


def activate_monitoring(
    scheduler: TradingDayScheduler,
) -> None:
    TradingDayMonitoringCoordinator(
        scheduler=scheduler
    ).activate_monitoring(
        activated_at=dt(
            9,
            21,
        )
    )


def make_coordinator(
    *,
    monitoring: bool = True,
):
    preparation, call_service, put_service = (
        make_preparation()
    )

    scheduler = make_waiting_scheduler()

    if monitoring:
        activate_monitoring(
            scheduler
        )

    coordinator = (
        TradingDayTickMonitoringCoordinator(
            scheduler=scheduler,
            preparation=preparation,
            call_level_service=call_service,
            put_level_service=put_service,
        )
    )

    return (
        coordinator,
        scheduler,
        preparation,
        call_service,
        put_service,
    )


def make_tick(
    *,
    security_id: str,
    symbol: str,
    price: float,
    timestamp: datetime,
) -> MarketTick:
    return MarketTick(
        exchange=Exchange.NFO,
        symbol=symbol,
        security_id=security_id,
        ltp=price,
        volume=0,
        timestamp=timestamp,
    )


def test_requires_separate_level_services() -> None:
    preparation, call_service, _ = (
        make_preparation()
    )

    scheduler = make_waiting_scheduler()

    with pytest.raises(
        ValueError,
        match=(
            "CALL and PUT monitoring must use separate "
            "DailyKSLevelService instances"
        ),
    ):
        TradingDayTickMonitoringCoordinator(
            scheduler=scheduler,
            preparation=preparation,
            call_level_service=call_service,
            put_level_service=call_service,
        )


def test_requires_ready_call_level_service() -> None:
    preparation, _, put_service = (
        make_preparation()
    )

    scheduler = make_waiting_scheduler()

    with pytest.raises(
        TradingDayTickMonitoringError,
        match=(
            "CALL DailyKSLevelService is not ready"
        ),
    ):
        TradingDayTickMonitoringCoordinator(
            scheduler=scheduler,
            preparation=preparation,
            call_level_service=DailyKSLevelService(),
            put_level_service=put_service,
        )


def test_rejects_level_service_ownership_mismatch() -> None:
    preparation, _, put_service = (
        make_preparation()
    )

    wrong_service, _ = make_level_service(
        security_id="99999",
        symbol="OTHER-OPTION",
        open_price=90.0,
        high=110.0,
        low=70.0,
        close=100.0,
    )

    scheduler = make_waiting_scheduler()

    with pytest.raises(
        TradingDayTickMonitoringError,
        match=(
            "CALL DailyKSLevelService does not own "
            "the prepared KS levels"
        ),
    ):
        TradingDayTickMonitoringCoordinator(
            scheduler=scheduler,
            preparation=preparation,
            call_level_service=wrong_service,
            put_level_service=put_service,
        )


def test_tick_is_ignored_before_monitoring() -> None:
    (
        coordinator,
        scheduler,
        preparation,
        _,
        _,
    ) = make_coordinator(
        monitoring=False
    )

    call_k5 = preparation.call_levels.k5

    assert (
        coordinator.process_tick(
            make_tick(
                security_id=CALL_SECURITY_ID,
                symbol=CALL_SYMBOL,
                price=call_k5 - 10.0,
                timestamp=dt(
                    9,
                    20,
                    59,
                ),
            )
        )
        == ()
    )

    activate_monitoring(
        scheduler
    )

    # If the pre-monitoring tick had primed LevelMonitor,
    # this would cross upward through K5. It must not.
    assert (
        coordinator.process_tick(
            make_tick(
                security_id=CALL_SECURITY_ID,
                symbol=CALL_SYMBOL,
                price=call_k5 + 1.0,
                timestamp=dt(
                    9,
                    21,
                    1,
                ),
            )
        )
        == ()
    )


def test_stale_920_tick_is_ignored_after_activation() -> None:
    (
        coordinator,
        _,
        preparation,
        _,
        _,
    ) = make_coordinator()

    call_k5 = preparation.call_levels.k5

    assert (
        coordinator.process_tick(
            make_tick(
                security_id=CALL_SECURITY_ID,
                symbol=CALL_SYMBOL,
                price=call_k5 - 5.0,
                timestamp=dt(
                    9,
                    20,
                    59,
                ),
            )
        )
        == ()
    )

    assert (
        coordinator.process_tick(
            make_tick(
                security_id=CALL_SECURITY_ID,
                symbol=CALL_SYMBOL,
                price=call_k5 + 1.0,
                timestamp=dt(
                    9,
                    21,
                    1,
                ),
            )
        )
        == ()
    )


def test_call_tick_routes_to_call_monitor() -> None:
    (
        coordinator,
        _,
        preparation,
        _,
        _,
    ) = make_coordinator()

    events = coordinator.process_tick(
        make_tick(
            security_id=CALL_SECURITY_ID,
            symbol=CALL_SYMBOL,
            price=preparation.call_levels.k5,
            timestamp=dt(
                9,
                21,
                1,
            ),
        )
    )

    assert len(events) == 1

    event = events[0]

    assert (
        event.instrument_security_id
        == CALL_SECURITY_ID
    )

    assert event.instrument_symbol == CALL_SYMBOL
    assert event.market_price == preparation.call_levels.k5
    assert event.level.value == "K5"
    assert event.event_type is LevelEventType.TOUCHED


def test_put_tick_routes_to_put_monitor() -> None:
    (
        coordinator,
        _,
        preparation,
        _,
        _,
    ) = make_coordinator()

    events = coordinator.process_tick(
        make_tick(
            security_id=PUT_SECURITY_ID,
            symbol=PUT_SYMBOL,
            price=preparation.put_levels.k5,
            timestamp=dt(
                9,
                21,
                1,
            ),
        )
    )

    assert len(events) == 1

    event = events[0]

    assert (
        event.instrument_security_id
        == PUT_SECURITY_ID
    )

    assert event.instrument_symbol == PUT_SYMBOL
    assert event.market_price == preparation.put_levels.k5
    assert event.level.value == "K5"


def test_call_and_put_monitor_state_is_independent() -> None:
    (
        coordinator,
        _,
        preparation,
        _,
        _,
    ) = make_coordinator()

    call_k5 = preparation.call_levels.k5
    put_k5 = preparation.put_levels.k5

    assert (
        coordinator.process_tick(
            make_tick(
                security_id=CALL_SECURITY_ID,
                symbol=CALL_SYMBOL,
                price=call_k5 - 10.0,
                timestamp=dt(
                    9,
                    21,
                    1,
                ),
            )
        )
        == ()
    )

    assert (
        coordinator.process_tick(
            make_tick(
                security_id=PUT_SECURITY_ID,
                symbol=PUT_SYMBOL,
                price=put_k5 + 10.0,
                timestamp=dt(
                    9,
                    21,
                    1,
                ),
            )
        )
        == ()
    )

    call_events = coordinator.process_tick(
        make_tick(
            security_id=CALL_SECURITY_ID,
            symbol=CALL_SYMBOL,
            price=call_k5 + 1.0,
            timestamp=dt(
                9,
                21,
                2,
            ),
        )
    )

    put_events = coordinator.process_tick(
        make_tick(
            security_id=PUT_SECURITY_ID,
            symbol=PUT_SYMBOL,
            price=put_k5 - 1.0,
            timestamp=dt(
                9,
                21,
                2,
            ),
        )
    )

    assert any(
        event.level.value == "K5"
        and event.event_type
        is LevelEventType.CROSSED_UP
        for event in call_events
    )

    assert any(
        event.level.value == "K5"
        and event.event_type
        is LevelEventType.CROSSED_DOWN
        for event in put_events
    )


def test_nifty_spot_tick_is_ignored() -> None:
    (
        coordinator,
        _,
        preparation,
        _,
        _,
    ) = make_coordinator()

    tick = MarketTick(
        exchange=Exchange.IDX,
        symbol="NIFTY 50",
        security_id="13",
        ltp=preparation.call_levels.k5,
        volume=0,
        timestamp=dt(
            9,
            21,
            1,
        ),
    )

    assert coordinator.process_tick(tick) == ()


def test_unselected_option_tick_is_ignored() -> None:
    coordinator, _, _, _, _ = (
        make_coordinator()
    )

    tick = make_tick(
        security_id="999999",
        symbol="NIFTY-25000-CE",
        price=200.0,
        timestamp=dt(
            9,
            21,
            1,
        ),
    )

    assert coordinator.process_tick(tick) == ()


def test_matching_security_id_wrong_symbol_is_ignored() -> None:
    (
        coordinator,
        _,
        preparation,
        _,
        _,
    ) = make_coordinator()

    events = coordinator.process_tick(
        make_tick(
            security_id=CALL_SECURITY_ID,
            symbol="WRONG-SYMBOL",
            price=preparation.call_levels.k5,
            timestamp=dt(
                9,
                21,
                1,
            ),
        )
    )

    assert events == ()


def test_wrong_trading_date_tick_is_ignored() -> None:
    (
        coordinator,
        _,
        preparation,
        _,
        _,
    ) = make_coordinator()

    events = coordinator.process_tick(
        make_tick(
            security_id=CALL_SECURITY_ID,
            symbol=CALL_SYMBOL,
            price=preparation.call_levels.k5,
            timestamp=dt(
                9,
                21,
                1,
                day=11,
            ),
        )
    )

    assert events == ()


def test_exit_only_blocks_entry_level_monitoring() -> None:
    (
        coordinator,
        scheduler,
        preparation,
        _,
        _,
    ) = make_coordinator()

    scheduler.transition(
        target_state=TradingDayState.EXIT_ONLY,
        transitioned_at=dt(
            15,
            15,
        ),
    )

    events = coordinator.process_tick(
        make_tick(
            security_id=CALL_SECURITY_ID,
            symbol=CALL_SYMBOL,
            price=preparation.call_levels.k5,
            timestamp=dt(
                15,
                15,
            ),
        )
    )

    assert events == ()


def test_non_market_tick_is_rejected() -> None:
    coordinator, _, _, _, _ = (
        make_coordinator()
    )

    with pytest.raises(
        TypeError,
        match="tick must be a MarketTick",
    ):
        coordinator.process_tick(
            object()
        )
