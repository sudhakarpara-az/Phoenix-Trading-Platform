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



def test_runtime_exposes_exact_owned_signal_engine() -> None:
    stack = make_runtime()

    assert (
        stack["runtime"].signal_engine
        is stack["signal_engine"]
    )



# ============================================================
# T14 accepted-signal entry lifecycle
# ============================================================

from dataclasses import dataclass as _entry_dataclass
from decimal import Decimal as _EntryDecimal
from types import SimpleNamespace as _EntryNS

from src.account.account_execution_gate import (
    AccountEntryBlockedError as _AccountEntryBlockedError,
)
from src.app.trading_day_runtime import (
    TradingDayEntryRuntimeCoordinator,
    TradingDayEntryRuntimeReason,
)
from src.execution.broker_execution_provider import (
    BrokerOrderSnapshot as _EntryBrokerOrderSnapshot,
)
from src.execution.execution_service import (
    EntrySubmissionUncertainError as _EntrySubmissionUncertainError,
)
from src.execution.execution_types import (
    BrokerOrderReference as _EntryBrokerOrderReference,
    BrokerOrderStatus as _EntryBrokerOrderStatus,
    ExecutionMode as _EntryExecutionMode,
    ExecutionResult as _EntryExecutionResult,
    OrderIntent as _EntryOrderIntent,
    OrderIntentId as _EntryOrderIntentId,
    OrderType as _EntryOrderType,
    TransactionType as _EntryTransactionType,
)


class _T14EntryRegistry:
    def __init__(self):
        self.positions = {}

    def get(self, position_id):
        return self.positions.get(
            position_id.value
        )

    def register(self, position):
        self.positions[
            position.position_id.value
        ] = position
        return position

    def replace(self, position):
        self.positions[
            position.position_id.value
        ] = position
        return position


class _T14EntryDailyRisk:
    def __init__(
        self,
        registry,
        *,
        allowed=True,
    ):
        self.registry = registry
        self.allowed = allowed

    def build_snapshot(
        self,
        *,
        trading_date,
        position_pnls,
        captured_at,
    ):
        return _EntryNS(
            trading_date=trading_date,
            new_entries_allowed=(
                self.allowed
            ),
            lock_reason=_EntryNS(
                value=(
                    "NONE"
                    if self.allowed
                    else "MANUAL_LOCK"
                )
            ),
            message=None,
        )


class _T14EntryExposure:
    def __init__(
        self,
        registry,
        *,
        allowed=True,
    ):
        self.registry = registry
        self.allowed = allowed

    def evaluate_new_position(
        self,
        *,
        quantity,
        stop_risk_points,
    ):
        return _EntryNS(
            eligible=self.allowed,
            reason=_EntryNS(
                value=(
                    "ELIGIBLE"
                    if self.allowed
                    else "MAX_OPEN_POSITIONS"
                )
            ),
            message=None,
            proposed_quantity=quantity,
            proposed_risk_amount=(
                quantity
                * stop_risk_points
            ),
        )


class _T14EntryPnLTracker:
    def __init__(self):
        self.states = {}

    def pnl_map(self):
        return {}

    def get(self, position_id):
        return self.states.get(
            position_id.value
        )

    def register(
        self,
        *,
        position,
        registered_at,
    ):
        state = _EntryNS(
            position_id=position.position_id,
            registered_at=registered_at,
        )

        self.states[
            position.position_id.value
        ] = state

        return state


@_entry_dataclass(
    frozen=True
)
class _T14EntryManaged:
    risk_id: object
    position: object
    open_quantity: int
    closed_quantity: int
    realized_pnl: float
    state: object
    stop_loss: object
    target: object | None
    created_at: datetime
    updated_at: datetime

    @property
    def position_id(self):
        return self.position.position_id


class _T14EntryInitializer:
    def __init__(
        self,
        registry,
    ):
        self.registry = registry

        self.stop_loss_policy = (
            _EntryNS(
                config=_EntryNS(
                    risk_points=15.0
                )
            )
        )

    def initialize(
        self,
        *,
        position,
        initialized_at,
        risk_id=None,
    ):
        managed = _T14EntryManaged(
            risk_id=(
                risk_id
                or _EntryNS(
                    value=(
                        "RISK:"
                        + position.position_id.value
                    )
                )
            ),
            position=position,
            open_quantity=65,
            closed_quantity=0,
            realized_pnl=0.0,
            state=_EntryNS(
                value="OPEN"
            ),
            stop_loss=_EntryNS(
                stop_price=85.5,
                risk_points=15.0,
            ),
            target=None,
            created_at=initialized_at,
            updated_at=initialized_at,
        )

        return self.registry.register(
            managed
        )


class _T14EntryTargetMapper:
    def map_target(
        self,
        *,
        position,
        levels,
        mapped_at,
    ):
        target = _EntryNS(
            executable_price=130.0,
            mapped_target_price=133.0,
            booking_zone_start=130.0,
            booking_zone_end=133.0,
        )

        return _EntryNS(
            mapped=True,
            mapping=_EntryNS(
                target_definition=target
            ),
        )


class _T14EntryFilledBuilder:
    def build(
        self,
        *,
        intent,
        broker_snapshot,
        created_at=None,
    ):
        return _EntryNS(
            position_id=_EntryNS(
                value="POS-T14-ENTRY"
            ),
            signal_id=(
                intent.signal.signal_id
            ),
            entry_intent_id=(
                intent.intent_id
            ),
            entry_broker_reference=(
                broker_snapshot
                .broker_reference
            ),
            selected_option=(
                intent.selected_option
            ),
            level=(
                intent.signal.level
            ),
            quantity=intent.quantity,
            entry_price=(
                broker_snapshot
                .average_price
            ),
            filled_at=(
                created_at
                or broker_snapshot.updated_at
            ),
            security_id=(
                intent.selected_option
                .security_id
            ),
            symbol=(
                intent.selected_option
                .symbol
            ),
        )


class _T14EntryGuard:
    def get(self, key):
        return None


class _T14EntryExecutionService:
    def __init__(
        self,
        *,
        snapshot,
    ):
        self.snapshot = snapshot
        self.refresh_calls = 0
        self.idempotency_guard = (
            _T14EntryGuard()
        )
        self.cancel_calls = 0

    def cancel_entry_order(
        self,
        *,
        intent,
        execution_result,
    ):
        self.cancel_calls += 1
        return self.snapshot

    def refresh_entry_order_status(
        self,
        *,
        intent,
        execution_result,
    ):
        self.refresh_calls += 1
        return self.snapshot


class _T14EntryAdapter:
    def __init__(
        self,
        execution_service,
    ):
        self.execution_service = (
            execution_service
        )

    def calculate_sizing(
        self,
        *,
        selected_option,
    ):
        return _EntryNS(
            requested_quantity=65,
            required_cash=(
                _EntryDecimal("6565.00")
            ),
            pricing=_EntryNS(
                limit_price=101.0
            ),
        )


class _T14EntryAccountGate:
    def __init__(
        self,
        entry_execution,
        *,
        mode="EXECUTE",
        broker_status=(
            _EntryBrokerOrderStatus.OPEN
        ),
    ):
        self.entry_execution = (
            entry_execution
        )

        self.mode = mode
        self.broker_status = (
            broker_status
        )

        self.calls = 0

    def execute_entry(
        self,
        *,
        signal,
        selected_option,
        required_cash,
        dry_run,
        requested_at,
    ):
        self.calls += 1

        if self.mode == "BLOCK":
            raise _AccountEntryBlockedError(
                eligibility=_EntryNS(
                    reason=_EntryNS(
                        value="INSUFFICIENT_FUNDS"
                    )
                )
            )

        intent = _EntryOrderIntent(
            intent_id=_EntryOrderIntentId(
                "ORD-T14-ENTRY"
            ),
            signal=signal,
            selected_option=(
                selected_option
            ),
            transaction_type=(
                _EntryTransactionType.BUY
            ),
            order_type=(
                _EntryOrderType.LIMIT
            ),
            quantity=65,
            limit_price=101.0,
            execution_mode=(
                _EntryExecutionMode.DRY_RUN
                if dry_run
                else _EntryExecutionMode.LIVE
            ),
            created_at=requested_at,
        )

        if self.mode == "UNCERTAIN":
            raise _EntrySubmissionUncertainError(
                intent=intent,
                cause=RuntimeError(
                    "simulated timeout"
                ),
            )

        reference = (
            _EntryBrokerOrderReference(
                broker_name=(
                    "DRY_RUN"
                    if dry_run
                    else "FAKE"
                ),
                order_id="ENTRY-1",
            )
        )

        execution_result = (
            _EntryExecutionResult(
                intent_id=intent.intent_id,
                success=(
                    dry_run
                    or self.broker_status
                    in {
                        _EntryBrokerOrderStatus
                        .PENDING,
                        _EntryBrokerOrderStatus
                        .OPEN,
                        _EntryBrokerOrderStatus
                        .PARTIALLY_FILLED,
                        _EntryBrokerOrderStatus
                        .FILLED,
                    }
                ),
                status=(
                    _EntryBrokerOrderStatus.FILLED
                    if dry_run
                    else self.broker_status
                ),
                broker_reference=reference,
                submitted_at=requested_at,
            )
        )

        execution = _EntryNS(
            intent=intent,
            execution_result=(
                execution_result
            ),
            eligibility=_EntryNS(
                eligible=True,
                reason=_EntryNS(
                    value="ELIGIBLE"
                ),
                message=None,
            ),
        )

        return _EntryNS(
            execution=execution,
            eligibility=_EntryNS(
                allowed=True
            ),
            evaluated_at=requested_at,
        )


def _make_t14_entry_stack(
    *,
    daily_allowed=True,
    exposure_allowed=True,
    account_mode="EXECUTE",
    broker_status=(
        _EntryBrokerOrderStatus.OPEN
    ),
    filled_quantity=0,
    average_price=None,
):
    signal_stack = make_runtime()

    registry = _T14EntryRegistry()

    snapshot = (
        _EntryBrokerOrderSnapshot(
            broker_reference=(
                _EntryBrokerOrderReference(
                    broker_name="FAKE",
                    order_id="ENTRY-1",
                )
            ),
            status=broker_status,
            quantity=65,
            filled_quantity=(
                filled_quantity
            ),
            average_price=(
                average_price
            ),
            updated_at=dt(
                10,
                0,
                1,
            ),
        )
    )

    execution_service = (
        _T14EntryExecutionService(
            snapshot=snapshot
        )
    )

    adapter = _T14EntryAdapter(
        execution_service
    )

    account_gate = (
        _T14EntryAccountGate(
            adapter,
            mode=account_mode,
            broker_status=(
                broker_status
            ),
        )
    )

    daily = _T14EntryDailyRisk(
        registry,
        allowed=daily_allowed,
    )

    exposure = _T14EntryExposure(
        registry,
        allowed=exposure_allowed,
    )

    pnl_tracker = (
        _T14EntryPnLTracker()
    )

    initializer = (
        _T14EntryInitializer(
            registry
        )
    )

    call_levels = _EntryNS(
        trading_date=TRADING_DATE,
        instrument_security_id=(
            signal_stack[
                "selected_call"
            ].security_id
        ),
        instrument_symbol=(
            signal_stack[
                "selected_call"
            ].symbol
        ),
    )

    put_levels = _EntryNS(
        trading_date=TRADING_DATE,
        instrument_security_id=(
            signal_stack[
                "selected_put"
            ].security_id
        ),
        instrument_symbol=(
            signal_stack[
                "selected_put"
            ].symbol
        ),
    )

    preparation = _EntryNS(
        selected_call=(
            signal_stack[
                "selected_call"
            ]
        ),
        selected_put=(
            signal_stack[
                "selected_put"
            ]
        ),
        call_levels=call_levels,
        put_levels=put_levels,
        is_ready=True,
    )

    coordinator = (
        TradingDayEntryRuntimeCoordinator(
            signal_runtime=(
                signal_stack["runtime"]
            ),
            entry_adapter=adapter,
            account_gate=account_gate,
            exposure_policy=exposure,
            daily_risk_manager=daily,
            pnl_tracker=pnl_tracker,
            filled_position_builder=(
                _T14EntryFilledBuilder()
            ),
            position_initializer=(
                initializer
            ),
            target_mapper=(
                _T14EntryTargetMapper()
            ),
            level_preparation=(
                preparation
            ),
        )
    )

    return {
        "signal_stack": signal_stack,
        "coordinator": coordinator,
        "registry": registry,
        "pnl_tracker": pnl_tracker,
        "execution_service": (
            execution_service
        ),
        "account_gate": account_gate,
    }


def _create_t14_signal_result(
    stack,
):
    return (
        stack["signal_stack"]
        ["runtime"]
        .process_event(
            make_event()
        )
    )


def test_entry_runtime_daily_risk_block_releases_m04_lock() -> None:
    stack = _make_t14_entry_stack(
        daily_allowed=False
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    result = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        result.reason
        is TradingDayEntryRuntimeReason
        .DAILY_RISK_BLOCKED
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 0
    )

    assert (
        stack["account_gate"].calls
        == 0
    )


def test_entry_runtime_exposure_block_releases_m04_lock() -> None:
    stack = _make_t14_entry_stack(
        exposure_allowed=False
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    result = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        result.reason
        is TradingDayEntryRuntimeReason
        .EXPOSURE_RISK_BLOCKED
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 0
    )

    assert (
        stack["account_gate"].calls
        == 0
    )


def test_entry_runtime_account_block_releases_m04_lock() -> None:
    stack = _make_t14_entry_stack(
        account_mode="BLOCK"
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    result = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        result.reason
        is TradingDayEntryRuntimeReason
        .ACCOUNT_BLOCKED
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 0
    )


def test_entry_runtime_uncertain_submission_retains_m04_lock() -> None:
    stack = _make_t14_entry_stack(
        account_mode="UNCERTAIN"
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    result = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        result.reason
        is TradingDayEntryRuntimeReason
        .RECONCILIATION_REQUIRED
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 1
    )

    assert (
        stack["coordinator"]
        .pending_count
        == 1
    )

    assert (
        stack["coordinator"]
        .get_pending_entry(
            signal_result
            .signal
            .signal_id
            .value
        )
        is not None
    )


def test_entry_runtime_zero_fill_cancel_releases_m04_lock() -> None:
    stack = _make_t14_entry_stack(
        broker_status=(
            _EntryBrokerOrderStatus
            .CANCELLED
        ),
        filled_quantity=0,
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    result = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        result.reason
        is TradingDayEntryRuntimeReason
        .ENTRY_CANCELLED
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 0
    )

    assert (
        stack["coordinator"]
        .pending_count
        == 0
    )


def test_entry_runtime_full_fill_creates_managed_position() -> None:
    stack = _make_t14_entry_stack(
        broker_status=(
            _EntryBrokerOrderStatus
            .FILLED
        ),
        filled_quantity=65,
        average_price=100.50,
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    result = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        result.reason
        is TradingDayEntryRuntimeReason
        .ENTRY_FILLED
    )

    assert result.position_opened is True
    assert result.filled_position is not None
    assert result.managed_position is not None

    assert (
        result.filled_position.entry_price
        == 100.50
    )

    assert (
        result.managed_position.target
        is not None
    )

    assert (
        len(stack["registry"].positions)
        == 1
    )

    assert (
        len(stack["pnl_tracker"].states)
        == 1
    )

    # Active real trade retains M04 contract+level lock.
    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 1
    )

    assert (
        stack["coordinator"]
        .pending_count
        == 0
    )


def test_entry_runtime_pending_signal_is_idempotent() -> None:
    stack = _make_t14_entry_stack(
        broker_status=(
            _EntryBrokerOrderStatus.OPEN
        )
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    first = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    second = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
                2,
            ),
        )
    )

    assert (
        first.reason
        is TradingDayEntryRuntimeReason
        .ENTRY_PENDING
    )

    assert second is first

    assert (
        stack["account_gate"].calls
        == 1
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 1
    )


def test_entry_runtime_dry_run_does_not_create_real_position() -> None:
    stack = _make_t14_entry_stack()

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    result = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=True,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        result.reason
        is TradingDayEntryRuntimeReason
        .DRY_RUN_COMPLETED
    )

    assert result.filled_position is None
    assert result.managed_position is None

    assert (
        len(stack["registry"].positions)
        == 0
    )

    assert (
        stack["execution_service"]
        .refresh_calls
        == 0
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 0
    )



class _T14BrokenIdempotencyGuard:
    def get(
        self,
        key,
    ):
        raise RuntimeError(
            "simulated idempotency inspection failure"
        )


def test_entry_runtime_broker_boundary_inspection_failure_is_fail_closed() -> None:
    stack = _make_t14_entry_stack()

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    stack[
        "execution_service"
    ].idempotency_guard = (
        _T14BrokenIdempotencyGuard()
    )

    assert (
        stack["coordinator"]
        ._broker_boundary_crossed(
            signal_result.signal
        )
        is True
    )

    # The accepted M04 signal remains owned because Phoenix
    # cannot prove the broker boundary was not crossed.
    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 1
    )


def test_entry_runtime_public_contracts_are_exported() -> None:
    from src.app import trading_day_runtime

    expected = {
        "TradingDayEntryReconciliationContext",
        "TradingDayEntryRuntimeCoordinator",
        "TradingDayEntryRuntimeError",
        "TradingDayEntryRuntimeReason",
        "TradingDayEntryRuntimeResult",
    }

    assert expected.issubset(
        set(
            trading_day_runtime.__all__
        )
    )



def test_entry_runtime_cancel_pending_batch_uses_broker_truth() -> None:
    stack = _make_t14_entry_stack(
        broker_status=(
            _EntryBrokerOrderStatus.OPEN
        ),
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    first = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        first.reason
        is TradingDayEntryRuntimeReason
        .ENTRY_PENDING
    )

    current = (
        stack["execution_service"]
        .snapshot
    )

    stack["execution_service"].snapshot = (
        _EntryBrokerOrderSnapshot(
            broker_reference=(
                current.broker_reference
            ),
            status=(
                _EntryBrokerOrderStatus
                .CANCELLED
            ),
            quantity=current.quantity,
            filled_quantity=0,
            average_price=None,
            updated_at=dt(
                10,
                0,
                5,
            ),
        )
    )

    results = (
        stack["coordinator"]
        .cancel_pending_entries(
            cancelled_at=dt(
                10,
                0,
                6,
            ),
        )
    )

    assert len(results) == 1

    assert (
        results[0].reason
        is TradingDayEntryRuntimeReason
        .ENTRY_CANCELLED
    )

    assert (
        stack["execution_service"]
        .cancel_calls
        == 1
    )

    assert (
        stack["coordinator"]
        .pending_count
        == 0
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 0
    )


def test_entry_runtime_cancel_unknown_remains_reconciliation_required() -> None:
    stack = _make_t14_entry_stack(
        broker_status=(
            _EntryBrokerOrderStatus.OPEN
        ),
    )

    signal_result = (
        _create_t14_signal_result(
            stack
        )
    )

    first = (
        stack["coordinator"]
        .process_signal_result(
            signal_result,
            dry_run=False,
            requested_at=dt(
                10,
                0,
            ),
        )
    )

    assert (
        first.reason
        is TradingDayEntryRuntimeReason
        .ENTRY_PENDING
    )

    current = (
        stack["execution_service"]
        .snapshot
    )

    stack["execution_service"].snapshot = (
        _EntryBrokerOrderSnapshot(
            broker_reference=(
                current.broker_reference
            ),
            status=(
                _EntryBrokerOrderStatus
                .UNKNOWN
            ),
            quantity=current.quantity,
            filled_quantity=0,
            average_price=None,
            updated_at=dt(
                10,
                0,
                5,
            ),
        )
    )

    results = (
        stack["coordinator"]
        .cancel_pending_entries(
            cancelled_at=dt(
                10,
                0,
                6,
            ),
        )
    )

    assert len(results) == 1

    assert (
        results[0].reason
        is TradingDayEntryRuntimeReason
        .RECONCILIATION_REQUIRED
    )

    assert (
        stack["coordinator"]
        .pending_count
        == 1
    )

    assert (
        stack["signal_stack"]
        ["level_locks"]
        .count()
        == 1
    )
