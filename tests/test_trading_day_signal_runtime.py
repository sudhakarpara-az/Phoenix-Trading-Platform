from datetime import (
    date,
    datetime,
)

import pytest

from src.app.trading_day_runtime import (
    TradingDaySignalRuntimeCoordinator,
    TradingDaySignalRuntimeError,
    TradingDaySignalRuntimeReason,
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
    TradingDayEntryGateCoordinator,
    TradingDayScheduler,
    TradingDayState,
)
from src.signals.duplicate_signal_guard import (
    DuplicateSignalGuard,
)
from src.signals.eligibility_policy import (
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
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    LevelEvent,
    LevelEventType,
)


TRADING_DATE = date(
    2026,
    8,
    7,
)

EXPIRY = date(
    2026,
    8,
    11,
)

CALL_SECURITY_ID = "41009"
CALL_SYMBOL = "NIFTY50-20260811-24450-CE"

PUT_SECURITY_ID = "41019"
PUT_SYMBOL = "NIFTY50-20260811-24650-PE"


def dt(
    hour: int,
    minute: int,
    second: int = 0,
) -> datetime:
    return datetime(
        2026,
        8,
        7,
        hour,
        minute,
        second,
    )


class FakeRuntimeGate:
    def __init__(
        self,
        *,
        allowed: bool = True,
    ) -> None:
        self.allowed = allowed
        self.calls = 0

    def can_accept_new_entries(
        self,
    ) -> bool:
        self.calls += 1
        return self.allowed


def make_selected_option(
    *,
    option_type: OptionType,
    security_id: str,
    symbol: str,
    strike: float,
) -> SelectedOption:
    delta = (
        0.60
        if option_type is OptionType.CALL
        else -0.60
    )

    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=symbol,
                security_id=security_id,
                option_type=option_type,
                strike=strike,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=100.0,
                bid=99.95,
                ask=100.05,
                volume=10000,
                open_interest=50000,
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


def make_selected_pair():
    return (
        make_selected_option(
            option_type=OptionType.CALL,
            security_id=CALL_SECURITY_ID,
            symbol=CALL_SYMBOL,
            strike=24450.0,
        ),
        make_selected_option(
            option_type=OptionType.PUT,
            security_id=PUT_SECURITY_ID,
            symbol=PUT_SYMBOL,
            strike=24650.0,
        ),
    )


def make_monitoring_scheduler(
) -> TradingDayScheduler:
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
            TradingDayState
            .WAITING_FOR_REFERENCE_CLOSE,
            dt(
                9,
                15,
            ),
        ),
        (
            TradingDayState
            .SELECTING_OPTIONS,
            dt(
                9,
                16,
            ),
        ),
        (
            TradingDayState
            .PREPARING_LEVELS,
            dt(
                9,
                16,
                1,
            ),
        ),
        (
            TradingDayState
            .WAITING_FOR_MONITORING,
            dt(
                9,
                17,
            ),
        ),
        (
            TradingDayState.MONITORING,
            dt(
                9,
                21,
            ),
        ),
    )

    for state, changed_at in transitions:
        scheduler.transition(
            target_state=state,
            transitioned_at=changed_at,
        )

    return scheduler


def make_signal_engine():
    level_locks = LevelLockManager()

    engine = SignalEngine(
        eligibility_policy=(
            SignalEligibilityPolicy()
        ),
        duplicate_guard=(
            DuplicateSignalGuard()
        ),
        level_lock_manager=level_locks,
        reentry_manager=(
            ReentryStateManager()
        ),
        signal_builder=(
            SignalBuilder()
        ),
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
    )

    return (
        engine,
        level_locks,
    )


def make_runtime(
    *,
    runtime_allowed: bool = True,
):
    scheduler = (
        make_monitoring_scheduler()
    )

    runtime_gate = FakeRuntimeGate(
        allowed=runtime_allowed
    )

    entry_gate = (
        TradingDayEntryGateCoordinator(
            scheduler=scheduler,
            runtime_gate=runtime_gate,
        )
    )

    signal_engine, level_locks = (
        make_signal_engine()
    )

    selected_call, selected_put = (
        make_selected_pair()
    )

    runtime = (
        TradingDaySignalRuntimeCoordinator(
            entry_gate=entry_gate,
            signal_engine=signal_engine,
            selected_call=selected_call,
            selected_put=selected_put,
        )
    )

    return {
        "runtime": runtime,
        "scheduler": scheduler,
        "runtime_gate": runtime_gate,
        "signal_engine": signal_engine,
        "level_locks": level_locks,
        "selected_call": selected_call,
        "selected_put": selected_put,
    }


def make_event(
    *,
    security_id: str = CALL_SECURITY_ID,
    symbol: str = CALL_SYMBOL,
    level: KSLevelName = KSLevelName.K5,
    timestamp: datetime | None = None,
) -> LevelEvent:
    return LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id=security_id,
        instrument_symbol=symbol,
        level=level,
        event_type=(
            LevelEventType.CROSSED_UP
        ),
        level_price=100.0,
        market_price=101.0,
        timestamp=(
            timestamp
            or dt(
                10,
                0,
            )
        ),
    )


def test_call_event_creates_call_signal_for_fixed_contract() -> None:
    stack = make_runtime()

    result = stack[
        "runtime"
    ].process_event(
        make_event()
    )

    assert result.created is True

    assert (
        result.reason
        is TradingDaySignalRuntimeReason.CREATED
    )

    assert (
        result.selected_option
        is stack["selected_call"]
    )

    assert (
        result.direction
        is SignalDirection.CALL
    )

    assert result.signal is not None

    assert (
        result.signal
        .instrument_security_id
        == CALL_SECURITY_ID
    )

    assert (
        result.signal.instrument_symbol
        == CALL_SYMBOL
    )

    assert (
        result.signal.direction
        is SignalDirection.CALL
    )

    assert (
        stack["level_locks"].is_locked(
            instrument_security_id=(
                CALL_SECURITY_ID
            ),
            level=EntryLevel.K5,
        )
        is True
    )


def test_put_event_creates_put_signal_for_fixed_contract() -> None:
    stack = make_runtime()

    result = stack[
        "runtime"
    ].process_event(
        make_event(
            security_id=(
                PUT_SECURITY_ID
            ),
            symbol=PUT_SYMBOL,
            level=KSLevelName.K6,
        )
    )

    assert result.created is True

    assert (
        result.selected_option
        is stack["selected_put"]
    )

    assert (
        result.direction
        is SignalDirection.PUT
    )

    assert result.signal is not None

    assert (
        result.signal
        .instrument_security_id
        == PUT_SECURITY_ID
    )

    assert (
        result.signal.direction
        is SignalDirection.PUT
    )


def test_runtime_block_occurs_before_m04_lock() -> None:
    stack = make_runtime(
        runtime_allowed=False
    )

    result = stack[
        "runtime"
    ].process_event(
        make_event()
    )

    assert result.created is False

    assert (
        result.reason
        is TradingDaySignalRuntimeReason
        .ENTRY_GATE_BLOCKED
    )

    assert (
        result.signal_result
        is None
    )

    assert (
        stack["runtime_gate"].calls
        == 1
    )

    assert (
        stack["level_locks"].count()
        == 0
    )


def test_scheduler_block_occurs_before_runtime_and_m04() -> None:
    stack = make_runtime()

    stack[
        "scheduler"
    ].transition(
        target_state=(
            TradingDayState.EXIT_ONLY
        ),
        transitioned_at=dt(
            15,
            15,
        ),
    )

    event = make_event(
        timestamp=dt(
            15,
            15,
        )
    )

    result = stack[
        "runtime"
    ].process_event(
        event
    )

    assert (
        result.reason
        is TradingDaySignalRuntimeReason
        .ENTRY_GATE_BLOCKED
    )

    # T10 short-circuits M08 when scheduler itself blocks.
    assert (
        stack["runtime_gate"].calls
        == 0
    )

    assert (
        stack["level_locks"].count()
        == 0
    )


def test_unselected_contract_is_ignored_before_gate() -> None:
    stack = make_runtime()

    result = stack[
        "runtime"
    ].process_event(
        make_event(
            security_id="99999",
            symbol="OTHER-CONTRACT",
        )
    )

    assert (
        result.reason
        is TradingDaySignalRuntimeReason
        .UNSELECTED_CONTRACT
    )

    assert result.signal is None

    assert (
        stack["runtime_gate"].calls
        == 0
    )

    assert (
        stack["level_locks"].count()
        == 0
    )


def test_selected_security_with_wrong_symbol_fails_closed() -> None:
    stack = make_runtime()

    with pytest.raises(
        TradingDaySignalRuntimeError,
        match=(
            "CALL event symbol does not match "
            "fixed selected CALL"
        ),
    ):
        stack[
            "runtime"
        ].process_event(
            make_event(
                security_id=(
                    CALL_SECURITY_ID
                ),
                symbol="WRONG-SYMBOL",
            )
        )

    assert (
        stack["runtime_gate"].calls
        == 0
    )

    assert (
        stack["level_locks"].count()
        == 0
    )


def test_m04_still_owns_1515_signal_cutoff() -> None:
    stack = make_runtime()

    result = stack[
        "runtime"
    ].process_event(
        make_event(
            timestamp=dt(
                15,
                15,
            )
        )
    )

    # Scheduler is intentionally still MONITORING here.
    # T10 therefore allows, after which M04 independently
    # rejects its own >=15:15 signal window.
    assert (
        result.reason
        is TradingDaySignalRuntimeReason
        .SIGNAL_REJECTED
    )

    assert result.signal_result is not None

    assert (
        result.signal_result.reason
        is SignalEngineReason.NOT_ELIGIBLE
    )

    assert (
        result.signal_result
        .eligibility_reason
        is EligibilityReason
        .AFTER_TRADING_WINDOW
    )

    assert (
        stack["level_locks"].count()
        == 0
    )


def test_same_k_level_is_independent_for_call_and_put() -> None:
    stack = make_runtime()

    call_result = stack[
        "runtime"
    ].process_event(
        make_event(
            security_id=(
                CALL_SECURITY_ID
            ),
            symbol=CALL_SYMBOL,
            level=KSLevelName.K5,
        )
    )

    put_result = stack[
        "runtime"
    ].process_event(
        make_event(
            security_id=(
                PUT_SECURITY_ID
            ),
            symbol=PUT_SYMBOL,
            level=KSLevelName.K5,
            timestamp=dt(
                10,
                0,
                1,
            ),
        )
    )

    assert call_result.created is True
    assert put_result.created is True

    assert (
        stack["level_locks"].count()
        == 2
    )


def test_invalid_selected_pair_is_rejected() -> None:
    scheduler = (
        make_monitoring_scheduler()
    )

    entry_gate = (
        TradingDayEntryGateCoordinator(
            scheduler=scheduler,
            runtime_gate=(
                FakeRuntimeGate()
            ),
        )
    )

    signal_engine, _ = (
        make_signal_engine()
    )

    call, put = make_selected_pair()

    with pytest.raises(
        ValueError,
        match="selected_call must be CALL",
    ):
        TradingDaySignalRuntimeCoordinator(
            entry_gate=entry_gate,
            signal_engine=signal_engine,
            selected_call=put,
            selected_put=put,
        )

    with pytest.raises(
        ValueError,
        match=(
            "selected_put must be PUT"
        ),
    ):
        TradingDaySignalRuntimeCoordinator(
            entry_gate=entry_gate,
            signal_engine=signal_engine,
            selected_call=call,
            selected_put=call,
        )


def test_non_level_event_is_rejected() -> None:
    stack = make_runtime()

    with pytest.raises(
        TypeError,
        match="event must be a LevelEvent",
    ):
        stack[
            "runtime"
        ].process_event(
            object()
        )
