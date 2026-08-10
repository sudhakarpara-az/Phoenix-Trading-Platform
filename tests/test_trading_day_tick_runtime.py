"""
M10-T14 Step 8C3G tick -> signal -> entry orchestration.
"""

from datetime import (
    date,
    datetime,
)
from types import SimpleNamespace

import pytest

from src.app.trading_day_runtime import (
    TradingDayEntryRuntimeReason,
    TradingDayEntryRuntimeResult,
    TradingDaySignalRuntimeReason,
    TradingDaySignalRuntimeResult,
    TradingDayTickRuntimeCoordinator,
    TradingDayTickRuntimeError,
)
from src.market.market_types import (
    Exchange,
    MarketTick,
)
from src.strategy.strategy_types import (
    KSLevelName,
    LevelEvent,
    LevelEventType,
)


TRADING_DATE = date(
    2026,
    8,
    10,
)


def dt(
    second: int = 1,
) -> datetime:
    return datetime(
        2026,
        8,
        10,
        9,
        21,
        second,
    )


def make_tick(
    *,
    price: float = 100.0,
    timestamp: datetime | None = None,
) -> MarketTick:
    return MarketTick(
        exchange=Exchange.NFO,
        symbol="NIFTY-24500-CE",
        security_id="41009",
        ltp=price,
        volume=0,
        timestamp=(
            timestamp
            if timestamp is not None
            else dt()
        ),
    )


def make_event(
    *,
    level: KSLevelName,
    level_price: float,
    event_type: LevelEventType,
    market_price: float,
    timestamp: datetime | None = None,
) -> LevelEvent:
    event_at = (
        timestamp
        if timestamp is not None
        else dt()
    )

    return LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id="41009",
        instrument_symbol="NIFTY-24500-CE",
        level=level,
        event_type=event_type,
        level_price=level_price,
        market_price=market_price,
        timestamp=event_at,
    )


class _FakeTickMonitor:
    def __init__(
        self,
        *,
        scheduler,
        selected_call,
        selected_put,
        events,
    ) -> None:
        self.scheduler = scheduler

        self.preparation = SimpleNamespace(
            selected_call=selected_call,
            selected_put=selected_put,
        )

        self.events = events
        self.calls = 0

    def process_tick(
        self,
        tick,
    ):
        self.calls += 1
        return self.events


class _FakeSignalRuntime:
    def __init__(
        self,
        *,
        scheduler,
        selected_call,
        selected_put,
    ) -> None:
        self.entry_gate = SimpleNamespace(
            scheduler=scheduler
        )

        self.selected_call = selected_call
        self.selected_put = selected_put

        self.calls = []

    def process_event(
        self,
        event,
    ):
        self.calls.append(
            event
        )

        return TradingDaySignalRuntimeResult(
            event=event,
            reason=(
                TradingDaySignalRuntimeReason
                .SIGNAL_REJECTED
            ),
            selected_option=None,
            direction=None,
            entry_gate_decision=None,
            signal_result=None,
        )


class _FakeEntryRuntime:
    def __init__(
        self,
        *,
        signal_runtime,
    ) -> None:
        self.signal_runtime = signal_runtime
        self.calls = []

    def process_signal_result(
        self,
        signal_runtime_result,
        *,
        dry_run,
        requested_at,
    ):
        self.calls.append(
            (
                signal_runtime_result,
                dry_run,
                requested_at,
            )
        )

        return TradingDayEntryRuntimeResult(
            signal_runtime_result=(
                signal_runtime_result
            ),
            reason=(
                TradingDayEntryRuntimeReason
                .SIGNAL_NOT_CREATED
            ),
        )


def make_stack(
    *,
    events,
):
    scheduler = object()

    selected_call = object()
    selected_put = object()

    monitor = _FakeTickMonitor(
        scheduler=scheduler,
        selected_call=selected_call,
        selected_put=selected_put,
        events=events,
    )

    signal_runtime = _FakeSignalRuntime(
        scheduler=scheduler,
        selected_call=selected_call,
        selected_put=selected_put,
    )

    entry_runtime = _FakeEntryRuntime(
        signal_runtime=signal_runtime,
    )

    runtime = (
        TradingDayTickRuntimeCoordinator(
            tick_monitor=monitor,
            signal_runtime=signal_runtime,
            entry_runtime=entry_runtime,
        )
    )

    return (
        runtime,
        monitor,
        signal_runtime,
        entry_runtime,
    )


def test_no_level_event_stops_before_signal_runtime() -> None:
    (
        runtime,
        monitor,
        signal_runtime,
        entry_runtime,
    ) = make_stack(
        events=(),
    )

    result = runtime.process_tick(
        make_tick(),
        dry_run=True,
    )

    assert monitor.calls == 1
    assert signal_runtime.calls == []
    assert entry_runtime.calls == []

    assert result.events == ()
    assert result.selected_event is None
    assert result.signal_runtime_result is None
    assert result.entry_runtime_result is None


def test_single_event_flows_to_signal_and_entry() -> None:
    tick = make_tick(
        price=121.0,
    )

    event = make_event(
        level=KSLevelName.K5,
        level_price=121.0,
        event_type=LevelEventType.TOUCHED,
        market_price=121.0,
    )

    (
        runtime,
        _,
        signal_runtime,
        entry_runtime,
    ) = make_stack(
        events=(event,),
    )

    result = runtime.process_tick(
        tick,
        dry_run=True,
    )

    assert result.selected_event is event

    assert signal_runtime.calls == [
        event
    ]

    assert len(
        entry_runtime.calls
    ) == 1

    (
        passed_signal_result,
        passed_dry_run,
        passed_requested_at,
    ) = entry_runtime.calls[0]

    assert (
        passed_signal_result
        is result.signal_runtime_result
    )

    assert passed_dry_run is True
    assert passed_requested_at == tick.timestamp

    assert (
        result.entry_runtime_result
        is not None
    )


def test_cross_up_selects_first_traversed_lowest_level() -> None:
    tick = make_tick(
        price=130.0,
    )

    k5 = make_event(
        level=KSLevelName.K5,
        level_price=120.0,
        event_type=LevelEventType.CROSSED_UP,
        market_price=130.0,
    )

    k6 = make_event(
        level=KSLevelName.K6,
        level_price=100.0,
        event_type=LevelEventType.CROSSED_UP,
        market_price=130.0,
    )

    k7 = make_event(
        level=KSLevelName.K7,
        level_price=70.0,
        event_type=LevelEventType.CROSSED_UP,
        market_price=130.0,
    )

    (
        runtime,
        _,
        signal_runtime,
        entry_runtime,
    ) = make_stack(
        events=(
            k5,
            k6,
            k7,
        ),
    )

    result = runtime.process_tick(
        tick,
        dry_run=False,
    )

    assert (
        result.selected_event
        is k7
    )

    assert signal_runtime.calls == [
        k7
    ]

    assert len(
        entry_runtime.calls
    ) == 1


def test_cross_down_selects_first_traversed_highest_level() -> None:
    tick = make_tick(
        price=60.0,
    )

    k5 = make_event(
        level=KSLevelName.K5,
        level_price=120.0,
        event_type=LevelEventType.CROSSED_DOWN,
        market_price=60.0,
    )

    k6 = make_event(
        level=KSLevelName.K6,
        level_price=100.0,
        event_type=LevelEventType.CROSSED_DOWN,
        market_price=60.0,
    )

    k7 = make_event(
        level=KSLevelName.K7,
        level_price=70.0,
        event_type=LevelEventType.CROSSED_DOWN,
        market_price=60.0,
    )

    (
        runtime,
        _,
        signal_runtime,
        entry_runtime,
    ) = make_stack(
        events=(
            k5,
            k6,
            k7,
        ),
    )

    result = runtime.process_tick(
        tick,
        dry_run=False,
    )

    assert (
        result.selected_event
        is k5
    )

    assert signal_runtime.calls == [
        k5
    ]

    assert len(
        entry_runtime.calls
    ) == 1


def test_ambiguous_multi_event_batch_fails_closed() -> None:
    tick = make_tick(
        price=100.0,
    )

    crossed = make_event(
        level=KSLevelName.K6,
        level_price=95.0,
        event_type=LevelEventType.CROSSED_UP,
        market_price=100.0,
    )

    touched = make_event(
        level=KSLevelName.K5,
        level_price=100.0,
        event_type=LevelEventType.TOUCHED,
        market_price=100.0,
    )

    (
        runtime,
        _,
        signal_runtime,
        entry_runtime,
    ) = make_stack(
        events=(
            crossed,
            touched,
        ),
    )

    with pytest.raises(
        TradingDayTickRuntimeError,
        match=(
            "ambiguous same-tick "
            "multi-level event batch"
        ),
    ):
        runtime.process_tick(
            tick,
            dry_run=False,
        )

    assert signal_runtime.calls == []
    assert entry_runtime.calls == []


def test_event_identity_mismatch_fails_before_signal() -> None:
    tick = make_tick(
        price=100.0,
    )

    wrong_event = LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id="99999",
        instrument_symbol="NIFTY-24500-CE",
        level=KSLevelName.K5,
        event_type=LevelEventType.TOUCHED,
        level_price=100.0,
        market_price=100.0,
        timestamp=dt(),
    )

    (
        runtime,
        _,
        signal_runtime,
        entry_runtime,
    ) = make_stack(
        events=(
            wrong_event,
        ),
    )

    with pytest.raises(
        TradingDayTickRuntimeError,
        match="security ID",
    ):
        runtime.process_tick(
            tick,
            dry_run=False,
        )

    assert signal_runtime.calls == []
    assert entry_runtime.calls == []


def test_requires_exact_shared_scheduler() -> None:
    scheduler_a = object()
    scheduler_b = object()

    selected_call = object()
    selected_put = object()

    monitor = _FakeTickMonitor(
        scheduler=scheduler_a,
        selected_call=selected_call,
        selected_put=selected_put,
        events=(),
    )

    signal_runtime = _FakeSignalRuntime(
        scheduler=scheduler_b,
        selected_call=selected_call,
        selected_put=selected_put,
    )

    entry_runtime = _FakeEntryRuntime(
        signal_runtime=signal_runtime,
    )

    with pytest.raises(
        ValueError,
        match=(
            "share the exact TradingDayScheduler"
        ),
    ):
        TradingDayTickRuntimeCoordinator(
            tick_monitor=monitor,
            signal_runtime=signal_runtime,
            entry_runtime=entry_runtime,
        )


def test_requires_exact_signal_runtime_ownership() -> None:
    scheduler = object()

    selected_call = object()
    selected_put = object()

    monitor = _FakeTickMonitor(
        scheduler=scheduler,
        selected_call=selected_call,
        selected_put=selected_put,
        events=(),
    )

    signal_runtime = _FakeSignalRuntime(
        scheduler=scheduler,
        selected_call=selected_call,
        selected_put=selected_put,
    )

    other_signal_runtime = _FakeSignalRuntime(
        scheduler=scheduler,
        selected_call=selected_call,
        selected_put=selected_put,
    )

    entry_runtime = _FakeEntryRuntime(
        signal_runtime=other_signal_runtime,
    )

    with pytest.raises(
        ValueError,
        match=(
            "entry runtime must own the exact "
            "signal runtime"
        ),
    ):
        TradingDayTickRuntimeCoordinator(
            tick_monitor=monitor,
            signal_runtime=signal_runtime,
            entry_runtime=entry_runtime,
        )


def test_public_tick_runtime_contracts_are_exported() -> None:
    import src.app.trading_day_runtime as module

    assert (
        "TradingDayTickRuntimeCoordinator"
        in module.__all__
    )

    assert (
        "TradingDayTickRuntimeError"
        in module.__all__
    )

    assert (
        "TradingDayTickRuntimeResult"
        in module.__all__
    )
