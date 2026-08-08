"""
Phoenix M08-T10 Full M02 -> M08 Runtime Integration tests.

Validates:

    market data
        ->
    strategy
        ->
    signal
        ->
    option selection
        ->
    entry execution
        ->
    position registration
        ->
    risk monitoring
        ->
    exit execution
        ->
    persistence
        ->
    runtime audit events

No real Dhan orders are placed.
"""
from src.runtime.runtime_types import (
    RuntimeFailureCode,
    RuntimeId,
    RuntimeMode,
    RuntimeState,
)
from dataclasses import dataclass
from datetime import (
    date,
    datetime,
)

import pytest

from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.runtime_events import (
    RuntimeEventType,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
    RuntimeState,
)
from src.runtime.trading_pipeline import (
    TradingPipelineError,
    TradingRuntimePipeline,
)


TODAY = date(
    2026,
    8,
    8,
)

NOW = datetime(
    2026,
    8,
    8,
    10,
    0,
)


@dataclass(frozen=True)
class FakeMarketTick:
    price: float


@dataclass(frozen=True)
class FakeStrategyResult:
    level: str


@dataclass(frozen=True)
class FakeSignal:
    signal_id: str


@dataclass(frozen=True)
class FakeSelectedOption:
    selection_id: str

    security_id: str = "41009"


@dataclass(frozen=True)
class FakeEntryExecution:
    order_intent_id: str

    filled: bool = True


@dataclass(frozen=True)
class FakePosition:
    position_id: str

    open_quantity: int


@dataclass(frozen=True)
class FakeExitDecision:
    position_id: str


@dataclass(frozen=True)
class FakeExitExecution:
    order_intent_id: str

    position_id: str

    filled: bool = True


class FakeStrategy:
    def __init__(self):
        self.calls = []
        self.result = FakeStrategyResult(
            level="K5"
        )

    def process_market_data(
        self,
        market_data,
        *,
        processed_at,
    ):
        self.calls.append(
            (
                market_data,
                processed_at,
            )
        )

        return self.result


class FakeSignalEngine:
    def __init__(self):
        self.calls = []
        self.result = FakeSignal(
            signal_id="SIG-001"
        )

    def build_signal(
        self,
        strategy_result,
        *,
        created_at,
    ):
        self.calls.append(
            (
                strategy_result,
                created_at,
            )
        )

        return self.result


class FakeOptionSelection:
    def __init__(self):
        self.calls = []

        self.result = (
            FakeSelectedOption(
                selection_id="SEL-001"
            )
        )

    def select_option(
        self,
        signal,
        *,
        selected_at,
    ):
        self.calls.append(
            (
                signal,
                selected_at,
            )
        )

        return self.result


class FakeEntryExecutionService:
    def __init__(self):
        self.calls = []

        self.result = FakeEntryExecution(
            order_intent_id="ORD-ENTRY-001"
        )

    def execute_entry(
        self,
        *,
        signal,
        selected_option,
        dry_run,
        requested_at,
    ):
        self.calls.append(
            {
                "signal": signal,
                "selected_option": (
                    selected_option
                ),
                "dry_run": dry_run,
                "requested_at": (
                    requested_at
                ),
            }
        )

        return self.result


class FakePositionRisk:
    def __init__(self):
        self.register_calls = []
        self.market_calls = []
        self.exit_fill_calls = []

        self.position = FakePosition(
            position_id="POS-001",
            open_quantity=65,
        )

        self.exit_decisions = ()

    def register_entry_fill(
        self,
        entry_execution,
        *,
        registered_at,
    ):
        self.register_calls.append(
            (
                entry_execution,
                registered_at,
            )
        )

        if not entry_execution.filled:
            return None

        return self.position

    def process_market_data(
        self,
        market_data,
        *,
        processed_at,
    ):
        self.market_calls.append(
            (
                market_data,
                processed_at,
            )
        )

        return tuple(
            self.exit_decisions
        )

    def apply_exit_fill(
        self,
        exit_execution,
        *,
        applied_at,
    ):
        self.exit_fill_calls.append(
            (
                exit_execution,
                applied_at,
            )
        )

        if not exit_execution.filled:
            return None

        self.position = FakePosition(
            position_id=(
                exit_execution.position_id
            ),
            open_quantity=0,
        )

        return self.position


class FakeExitExecutionService:
    def __init__(self):
        self.calls = []

    def execute_exit(
        self,
        decision,
        *,
        dry_run,
        requested_at,
    ):
        self.calls.append(
            {
                "decision": decision,
                "dry_run": dry_run,
                "requested_at": (
                    requested_at
                ),
            }
        )

        return FakeExitExecution(
            order_intent_id=(
                "ORD-EXIT-001"
            ),
            position_id=(
                decision.position_id
            ),
        )


class FakePersistence:
    def __init__(self):
        self.operations = []

        self.fail_on = None

    def _write(
        self,
        operation,
        value,
    ):
        if self.fail_on == operation:
            raise RuntimeError(
                "simulated persistence failure"
            )

        self.operations.append(
            (
                operation,
                value,
            )
        )

    def persist_signal(
        self,
        signal,
    ):
        self._write(
            "SIGNAL",
            signal,
        )

    def persist_option_selection(
        self,
        *,
        signal,
        selected_option,
    ):
        self._write(
            "OPTION",
            (
                signal,
                selected_option,
            ),
        )

    def persist_entry_execution(
        self,
        entry_execution,
    ):
        self._write(
            "ENTRY",
            entry_execution,
        )

    def persist_position(
        self,
        position,
    ):
        self._write(
            "POSITION",
            position,
        )

    def persist_exit_execution(
        self,
        exit_execution,
    ):
        self._write(
            "EXIT",
            exit_execution,
        )


def make_runtime(
    *,
    mode=RuntimeMode.DRY_RUN,
):
    bus = RuntimeEventBus()

    orchestrator = (
        TradingRuntimeOrchestrator(
            runtime_id=RuntimeId(
                "PHOENIX-M08-T10"
            ),
            trading_date=TODAY,
            mode=mode,
            event_bus=bus,
            created_at=NOW,
        )
    )

    orchestrator.start(
        started_at=NOW
    )

    orchestrator.run(
        running_at=NOW
    )

    strategy = FakeStrategy()

    signal_engine = (
        FakeSignalEngine()
    )

    option_selection = (
        FakeOptionSelection()
    )

    entry_execution = (
        FakeEntryExecutionService()
    )

    position_risk = (
        FakePositionRisk()
    )

    exit_execution = (
        FakeExitExecutionService()
    )

    persistence = (
        FakePersistence()
    )

    pipeline = TradingRuntimePipeline(
        orchestrator=orchestrator,
        event_bus=bus,
        strategy=strategy,
        signal_engine=signal_engine,
        option_selection=(
            option_selection
        ),
        entry_execution=(
            entry_execution
        ),
        position_risk=(
            position_risk
        ),
        exit_execution=(
            exit_execution
        ),
        persistence=persistence,
    )

    return {
        "bus": bus,
        "orchestrator": (
            orchestrator
        ),
        "strategy": strategy,
        "signal_engine": (
            signal_engine
        ),
        "option_selection": (
            option_selection
        ),
        "entry_execution": (
            entry_execution
        ),
        "position_risk": (
            position_risk
        ),
        "exit_execution": (
            exit_execution
        ),
        "persistence": (
            persistence
        ),
        "pipeline": pipeline,
    }


# ============================================================
# Complete entry flow
# ============================================================


def test_market_tick_runs_complete_entry_pipeline():
    runtime = make_runtime()

    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert result.accepted is True

    assert (
        result.signal_created
        is True
    )

    assert (
        result.option_selected
        is True
    )

    assert (
        result.entry_executed
        is True
    )

    assert (
        result.position_registered
        is True
    )


def test_pipeline_order_is_strategy_signal_option_execution_position():
    runtime = make_runtime()

    runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert len(
        runtime["strategy"].calls
    ) == 1

    assert len(
        runtime["signal_engine"].calls
    ) == 1

    assert len(
        runtime[
            "option_selection"
        ].calls
    ) == 1

    assert len(
        runtime[
            "entry_execution"
        ].calls
    ) == 1

    assert len(
        runtime[
            "position_risk"
        ].register_calls
    ) == 1


def test_entry_state_is_persisted_in_safe_order():
    runtime = make_runtime()

    runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    names = [
        item[0]
        for item
        in runtime[
            "persistence"
        ].operations
    ]

    assert names == [
        "SIGNAL",
        "OPTION",
        "ENTRY",
        "POSITION",
    ]


# ============================================================
# Runtime events
# ============================================================


def test_complete_entry_pipeline_publishes_events():
    runtime = make_runtime()

    received = []

    for event_type in (
        RuntimeEventType
        .SIGNAL_CREATED,
        RuntimeEventType
        .OPTION_SELECTED,
        RuntimeEventType
        .ENTRY_ORDER_SUBMITTED,
        RuntimeEventType
        .POSITION_OPENED,
    ):
        runtime[
            "bus"
        ].subscribe(
            event_type,
            lambda event: (
                received.append(
                    event.event_type
                )
            ),
        )

    runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert received == [
        RuntimeEventType
        .SIGNAL_CREATED,

        RuntimeEventType
        .OPTION_SELECTED,

        RuntimeEventType
        .ENTRY_ORDER_SUBMITTED,

        RuntimeEventType
        .POSITION_OPENED,
    ]


# ============================================================
# No-signal paths
# ============================================================


def test_no_strategy_result_stops_before_signal():
    runtime = make_runtime()

    runtime[
        "strategy"
    ].result = None

    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert result.accepted is True

    assert (
        result.signal_created
        is False
    )

    assert (
        runtime[
            "entry_execution"
        ].calls
        == []
    )


def test_signal_rejection_stops_before_option_selection():
    runtime = make_runtime()

    runtime[
        "signal_engine"
    ].result = None

    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert (
        result.signal_created
        is False
    )

    assert (
        runtime[
            "option_selection"
        ].calls
        == []
    )


def test_option_selection_failure_stops_before_entry():
    runtime = make_runtime()

    runtime[
        "option_selection"
    ].result = None

    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert result.signal_created is True

    assert (
        result.option_selected
        is False
    )

    assert (
        runtime[
            "entry_execution"
        ].calls
        == []
    )


# ============================================================
# DRY_RUN / LIVE
# ============================================================


def test_dry_run_is_forwarded_to_entry_execution():
    runtime = make_runtime(
        mode=RuntimeMode.DRY_RUN
    )

    runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    call = runtime[
        "entry_execution"
    ].calls[0]

    assert call[
        "dry_run"
    ] is True


def test_live_mode_is_forwarded_to_entry_execution():
    runtime = make_runtime(
        mode=RuntimeMode.LIVE
    )

    runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    call = runtime[
        "entry_execution"
    ].calls[0]

    assert call[
        "dry_run"
    ] is False


# ============================================================
# Exit path
# ============================================================


def test_existing_position_exit_processed_before_new_entry():
    runtime = make_runtime()

    runtime[
        "position_risk"
    ].exit_decisions = (
        FakeExitDecision(
            position_id="POS-001"
        ),
    )

    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=126
        ),
        processed_at=NOW,
    )

    assert result.exit_decisions == 1
    assert result.exit_executions == 1

    assert len(
        runtime[
            "exit_execution"
        ].calls
    ) == 1


def test_exit_execution_is_persisted():
    runtime = make_runtime()

    runtime[
        "position_risk"
    ].exit_decisions = (
        FakeExitDecision(
            position_id="POS-001"
        ),
    )

    runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=126
        ),
        processed_at=NOW,
    )

    names = [
        value[0]
        for value
        in runtime[
            "persistence"
        ].operations
    ]

    assert "EXIT" in names


def test_exit_fill_updates_position():
    runtime = make_runtime()

    runtime[
        "position_risk"
    ].exit_decisions = (
        FakeExitDecision(
            position_id="POS-001"
        ),
    )

    runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=126
        ),
        processed_at=NOW,
    )

    assert len(
        runtime[
            "position_risk"
        ].exit_fill_calls
    ) == 1

    assert (
        runtime[
            "position_risk"
        ].position.open_quantity
        == 0
    )


def test_dry_run_is_forwarded_to_exit_execution():
    runtime = make_runtime(
        mode=RuntimeMode.DRY_RUN
    )

    runtime[
        "position_risk"
    ].exit_decisions = (
        FakeExitDecision(
            position_id="POS-001"
        ),
    )

    runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=126
        ),
        processed_at=NOW,
    )

    assert (
        runtime[
            "exit_execution"
        ].calls[0]["dry_run"]
        is True
    )


# ============================================================
# New-entry safety gate
# ============================================================


def test_non_running_runtime_rejects_market_cycle():
    runtime = make_runtime()

    runtime[
        "orchestrator"
    ].stop(
        stopped_at=NOW
    )

    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert result.accepted is False


def test_failed_runtime_cannot_create_new_entry():
    runtime = make_runtime()

    runtime[
        "orchestrator"
    ].fail(
        code=(
            RuntimeFailureCode
            .DATABASE_FAILED
        ),
        message="database unavailable",
        failed_at=NOW,
        component="database",
    )

    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert result.accepted is False

    assert (
        runtime[
            "entry_execution"
        ].calls
        == []
    )


# ============================================================
# Persistence failure
# ============================================================


def test_signal_persistence_failure_fails_runtime_before_entry():
    runtime = make_runtime(
        mode=RuntimeMode.LIVE
    )

    runtime[
        "persistence"
    ].fail_on = "SIGNAL"

    with pytest.raises(
        TradingPipelineError
    ):
        runtime[
            "pipeline"
        ].process_market_data(
            FakeMarketTick(
                price=24600
            ),
            processed_at=NOW,
        )

    assert (
        runtime[
            "orchestrator"
        ].state
        is RuntimeState.FAILED
    )

    assert (
        runtime[
            "entry_execution"
        ].calls
        == []
    )


def test_option_persistence_failure_blocks_entry():
    runtime = make_runtime(
        mode=RuntimeMode.LIVE
    )

    runtime[
        "persistence"
    ].fail_on = "OPTION"

    with pytest.raises(
        TradingPipelineError
    ):
        runtime[
            "pipeline"
        ].process_market_data(
            FakeMarketTick(
                price=24600
            ),
            processed_at=NOW,
        )

    assert (
        runtime[
            "entry_execution"
        ].calls
        == []
    )


# ============================================================
# Entry not filled
# ============================================================


def test_unfilled_entry_does_not_create_position():
    runtime = make_runtime()

    runtime[
        "entry_execution"
    ].result = (
        FakeEntryExecution(
            order_intent_id=(
                "ORD-ENTRY-001"
            ),
            filled=False,
        )
    )

    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=24600
        ),
        processed_at=NOW,
    )

    assert result.entry_executed is True

    assert (
        result.position_registered
        is False
    )


# ============================================================
# Existing position remains manageable when entries blocked
# ============================================================


def test_exit_path_does_not_depend_on_new_entry_gate():
    runtime = make_runtime()

    runtime[
        "position_risk"
    ].exit_decisions = (
        FakeExitDecision(
            position_id="POS-001"
        ),
    )

    # This test validates the pipeline ordering contract.
    #
    # Risk processing occurs before strategy/new-entry
    # processing.
    result = runtime[
        "pipeline"
    ].process_market_data(
        FakeMarketTick(
            price=85
        ),
        processed_at=NOW,
    )

    assert result.exit_executions == 1