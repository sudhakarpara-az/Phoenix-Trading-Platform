"""
Phoenix M08 full trading runtime pipeline boundary.

Coordinates the already-completed M02-M07 engines through
narrow runtime ports.

This module does NOT implement:

    - market-data calculations
    - KS strategy calculations
    - signal rules
    - option selection
    - order pricing
    - broker execution
    - position risk calculations

Those remain owned by M02-M07.

M08 owns sequencing, safety gates, runtime events and
application-level failure handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import (
    Any,
    Protocol,
)

from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.runtime_events import (
    RuntimeEvent,
    RuntimeEventType,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeFailureCode,
    RuntimeMode,
    RuntimeState,
)


# ============================================================
# Runtime-facing ports
# ============================================================


class StrategyRuntimePort(
    Protocol,
):
    def process_market_data(
        self,
        market_data: Any,
        *,
        processed_at: datetime,
    ) -> Any | None:
        ...


class SignalRuntimePort(
    Protocol,
):
    def build_signal(
        self,
        strategy_result: Any,
        *,
        created_at: datetime,
    ) -> Any | None:
        ...


class OptionSelectionRuntimePort(
    Protocol,
):
    def select_option(
        self,
        signal: Any,
        *,
        selected_at: datetime,
    ) -> Any | None:
        ...


class EntryExecutionRuntimePort(
    Protocol,
):
    def execute_entry(
        self,
        *,
        signal: Any,
        selected_option: Any,
        dry_run: bool,
        requested_at: datetime,
    ) -> Any:
        ...


class PositionRiskRuntimePort(
    Protocol,
):
    def register_entry_fill(
        self,
        entry_execution: Any,
        *,
        registered_at: datetime,
    ) -> Any | None:
        ...

    def process_market_data(
        self,
        market_data: Any,
        *,
        processed_at: datetime,
    ) -> tuple[
        Any,
        ...
    ]:
        ...

    def apply_exit_fill(
        self,
        exit_execution: Any,
        *,
        applied_at: datetime,
    ) -> Any | None:
        ...


class ExitExecutionRuntimePort(
    Protocol,
):
    def execute_exit(
        self,
        exit_decision: Any,
        *,
        dry_run: bool,
        requested_at: datetime,
    ) -> Any:
        ...


class TradingPersistencePort(
    Protocol,
):
    """
    Runtime persistence boundary.

    Concrete implementation may delegate to T04 repositories.
    """

    def persist_signal(
        self,
        signal: Any,
    ) -> None:
        ...

    def persist_option_selection(
        self,
        *,
        signal: Any,
        selected_option: Any,
    ) -> None:
        ...

    def persist_entry_execution(
        self,
        entry_execution: Any,
    ) -> None:
        ...

    def persist_position(
        self,
        position: Any,
    ) -> None:
        ...

    def persist_exit_execution(
        self,
        exit_execution: Any,
    ) -> None:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class MarketProcessingResult:
    accepted: bool

    signal_created: bool = False

    option_selected: bool = False

    entry_executed: bool = False

    position_registered: bool = False

    exit_decisions: int = 0

    exit_executions: int = 0


class TradingPipelineError(
    RuntimeError
):
    pass


class TradingRuntimePipeline:
    """
    Application-level M02 -> M08 trading pipeline.

    One process_market_data() invocation represents one
    deterministic runtime processing cycle.
    """

    def __init__(
        self,
        *,
        orchestrator:
            TradingRuntimeOrchestrator,
        event_bus:
            RuntimeEventBus,
        strategy:
            StrategyRuntimePort,
        signal_engine:
            SignalRuntimePort,
        option_selection:
            OptionSelectionRuntimePort,
        entry_execution:
            EntryExecutionRuntimePort,
        position_risk:
            PositionRiskRuntimePort,
        exit_execution:
            ExitExecutionRuntimePort,
        persistence:
            TradingPersistencePort,
    ) -> None:
        self._orchestrator = orchestrator

        self._event_bus = event_bus

        self._strategy = strategy

        self._signal_engine = (
            signal_engine
        )

        self._option_selection = (
            option_selection
        )

        self._entry_execution = (
            entry_execution
        )

        self._position_risk = (
            position_risk
        )

        self._exit_execution = (
            exit_execution
        )

        self._persistence = (
            persistence
        )

    # ========================================================
    # Market cycle
    # ========================================================

    def process_market_data(
        self,
        market_data: Any,
        *,
        processed_at: datetime,
    ) -> MarketProcessingResult:
        """
        Process one M02 market-data update.

        Existing M07 positions are evaluated first.

        New entry processing occurs only if the runtime-level
        new-entry gate remains open.
        """

        if (
            self._orchestrator.state
            is not RuntimeState.RUNNING
        ):
            return MarketProcessingResult(
                accepted=False
            )

        try:
            # ------------------------------------------------
            # Existing position management first.
            #
            # Existing exposure must remain manageable even if
            # entry creation is blocked later.
            # ------------------------------------------------

            exit_decisions = (
                self._position_risk
                .process_market_data(
                    market_data,
                    processed_at=processed_at,
                )
            )

            exit_execution_count = 0

            for decision in exit_decisions:
                self._execute_exit(
                    decision=decision,
                    requested_at=processed_at,
                )

                exit_execution_count += 1

            # ------------------------------------------------
            # Runtime may manage exits while refusing new BUYs.
            # ------------------------------------------------

            if not (
                self._orchestrator
                .can_accept_new_entries()
            ):
                return MarketProcessingResult(
                    accepted=True,
                    exit_decisions=len(
                        exit_decisions
                    ),
                    exit_executions=(
                        exit_execution_count
                    ),
                )

            # ------------------------------------------------
            # M03
            # ------------------------------------------------

            strategy_result = (
                self._strategy
                .process_market_data(
                    market_data,
                    processed_at=processed_at,
                )
            )

            if strategy_result is None:
                return MarketProcessingResult(
                    accepted=True,
                    exit_decisions=len(
                        exit_decisions
                    ),
                    exit_executions=(
                        exit_execution_count
                    ),
                )

            # ------------------------------------------------
            # M04
            # ------------------------------------------------

            signal = (
                self._signal_engine
                .build_signal(
                    strategy_result,
                    created_at=processed_at,
                )
            )

            if signal is None:
                return MarketProcessingResult(
                    accepted=True,
                    exit_decisions=len(
                        exit_decisions
                    ),
                    exit_executions=(
                        exit_execution_count
                    ),
                )

            # Persist before downstream broker-sensitive work.
            self._persistence.persist_signal(
                signal
            )

            signal_event = (
                self._publish(
                    RuntimeEventType
                    .SIGNAL_CREATED,
                    processed_at,
                    payload={
                        "entity_type": "SIGNAL",
                        "entity_id": (
                            self._entity_id(
                                signal,
                                "signal_id",
                            )
                        ),
                    },
                )
            )

            # ------------------------------------------------
            # M05
            # ------------------------------------------------

            selected_option = (
                self._option_selection
                .select_option(
                    signal,
                    selected_at=processed_at,
                )
            )

            if selected_option is None:
                self._publish(
                    RuntimeEventType
                    .OPTION_SELECTION_FAILED,
                    processed_at,
                    causation_id=(
                        signal_event.event_id
                    ),
                )

                return MarketProcessingResult(
                    accepted=True,
                    signal_created=True,
                    exit_decisions=len(
                        exit_decisions
                    ),
                    exit_executions=(
                        exit_execution_count
                    ),
                )

            self._persistence.persist_option_selection(
                signal=signal,
                selected_option=selected_option,
            )

            selection_event = (
                self._publish(
                    RuntimeEventType
                    .OPTION_SELECTED,
                    processed_at,
                    causation_id=(
                        signal_event.event_id
                    ),
                    payload={
                        "entity_type": (
                            "OPTION_SELECTION"
                        ),
                        "entity_id": (
                            self._entity_id(
                                selected_option,
                                "selection_id",
                                fallback=(
                                    self._entity_id(
                                        signal,
                                        "signal_id",
                                    )
                                ),
                            )
                        ),
                    },
                )
            )

            # ------------------------------------------------
            # M06 BUY
            # ------------------------------------------------

            dry_run = (
                self._orchestrator.mode
                is RuntimeMode.DRY_RUN
            )

            entry_execution = (
                self._entry_execution
                .execute_entry(
                    signal=signal,
                    selected_option=(
                        selected_option
                    ),
                    dry_run=dry_run,
                    requested_at=processed_at,
                )
            )

            self._persistence.persist_entry_execution(
                entry_execution
            )

            entry_event = (
                self._publish(
                    RuntimeEventType
                    .ENTRY_ORDER_SUBMITTED,
                    processed_at,
                    causation_id=(
                        selection_event.event_id
                    ),
                    payload={
                        "entity_type": "ORDER",
                        "entity_id": (
                            self._entity_id(
                                entry_execution,
                                "order_intent_id",
                            )
                        ),
                    },
                )
            )

            # ------------------------------------------------
            # M07 registration only when M06 reports a
            # concrete fill/position object.
            # ------------------------------------------------

            position = (
                self._position_risk
                .register_entry_fill(
                    entry_execution,
                    registered_at=processed_at,
                )
            )

            if position is None:
                return MarketProcessingResult(
                    accepted=True,
                    signal_created=True,
                    option_selected=True,
                    entry_executed=True,
                    exit_decisions=len(
                        exit_decisions
                    ),
                    exit_executions=(
                        exit_execution_count
                    ),
                )

            self._persistence.persist_position(
                position
            )

            self._publish(
                RuntimeEventType
                .POSITION_OPENED,
                processed_at,
                causation_id=(
                    entry_event.event_id
                ),
                payload={
                    "entity_type": "POSITION",
                    "entity_id": (
                        self._entity_id(
                            position,
                            "position_id",
                        )
                    ),
                },
            )

            return MarketProcessingResult(
                accepted=True,
                signal_created=True,
                option_selected=True,
                entry_executed=True,
                position_registered=True,
                exit_decisions=len(
                    exit_decisions
                ),
                exit_executions=(
                    exit_execution_count
                ),
            )

        except Exception as exc:
            self._orchestrator.fail(
                code=(
                    RuntimeFailureCode
                    .INTERNAL_ERROR
                ),
                message=(
                    "trading runtime pipeline failed: "
                    f"{exc}"
                ),
                failed_at=processed_at,
                component=(
                    "trading-runtime-pipeline"
                ),
                recoverable=True,
            )

            raise TradingPipelineError(
                "trading runtime pipeline failed"
            ) from exc

    # ========================================================
    # Exit path
    # ========================================================

    def _execute_exit(
        self,
        *,
        decision: Any,
        requested_at: datetime,
    ) -> None:
        """
        Exit execution deliberately does NOT depend on
        can_accept_new_entries().

        Existing risk must remain manageable when BUYs are
        disabled.
        """

        dry_run = (
            self._orchestrator.mode
            is RuntimeMode.DRY_RUN
        )

        execution = (
            self._exit_execution
            .execute_exit(
                decision,
                dry_run=dry_run,
                requested_at=requested_at,
            )
        )

        self._persistence.persist_exit_execution(
            execution
        )

        updated_position = (
            self._position_risk
            .apply_exit_fill(
                execution,
                applied_at=requested_at,
            )
        )

        if updated_position is not None:
            self._persistence.persist_position(
                updated_position
            )

    # ========================================================
    # Events
    # ========================================================

    def _publish(
        self,
        event_type: RuntimeEventType,
        occurred_at: datetime,
        *,
        payload=None,
        causation_id: str | None = None,
    ) -> RuntimeEvent:
        event = RuntimeEvent.create(
            runtime_id=(
                self._orchestrator.runtime_id
            ),
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            correlation_id=(
                self._orchestrator
                .runtime_id.value
            ),
            causation_id=causation_id,
        )

        self._event_bus.publish(
            event
        )

        return event

    @staticmethod
    def _entity_id(
        value: Any,
        attribute: str,
        *,
        fallback: str | None = None,
    ) -> str | None:
        candidate = getattr(
            value,
            attribute,
            None,
        )

        if candidate is None:
            return fallback

        raw = getattr(
            candidate,
            "value",
            candidate,
        )

        return str(
            raw
        )