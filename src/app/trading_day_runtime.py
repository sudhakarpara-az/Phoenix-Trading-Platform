"""
Phoenix M10 trading-day application runtime integration.

This module is an application-level composition boundary.

T14 Step 7 integrates:

    selected-option LevelEvent
        ->
    M10 + M08 entry gate
        ->
    fixed CE/PE direction resolution
        ->
    existing M04 SignalEngine

Important:

    - CALL/PUT is derived from the fixed morning-selected contract.
    - M05 is NOT invoked again after a level event.
    - M10/M08 entry permission is checked before M04 acquires a
      contract+level signal lock.
    - Existing M04 eligibility, duplicate, lock and re-entry
      policies remain authoritative.
    - No broker execution or position creation belongs here yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.option_selection.option_types import (
    OptionType,
    SelectedOption,
)
from src.services.scheduler import (
    TradingDayEntryGateCoordinator,
    TradingDayEntryGateDecision,
)
from src.signals.eligibility_policy import (
    EligibilityContext,
)
from src.signals.signal_engine import (
    SignalEngine,
    SignalEngineResult,
)
from src.signals.signal_types import (
    SignalDirection,
    TradingSignal,
)
from src.strategy.strategy_types import (
    LevelEvent,
    StrategySessionState,
)


class TradingDaySignalRuntimeReason(
    str,
    Enum,
):
    """
    Outcome of routing one T09 LevelEvent toward M04.
    """

    CREATED = "CREATED"

    UNSELECTED_CONTRACT = (
        "UNSELECTED_CONTRACT"
    )

    ENTRY_GATE_BLOCKED = (
        "ENTRY_GATE_BLOCKED"
    )

    SIGNAL_REJECTED = (
        "SIGNAL_REJECTED"
    )


class TradingDaySignalRuntimeError(
    RuntimeError
):
    """
    Fixed selected-contract ownership could not be proven.
    """


@dataclass(
    frozen=True,
    slots=True,
)
class TradingDaySignalRuntimeResult:
    """
    Result of processing one selected-option LevelEvent.
    """

    event: LevelEvent

    reason: TradingDaySignalRuntimeReason

    selected_option: SelectedOption | None

    direction: SignalDirection | None

    entry_gate_decision: (
        TradingDayEntryGateDecision | None
    )

    signal_result: SignalEngineResult | None

    @property
    def signal(
        self,
    ) -> TradingSignal | None:
        if self.signal_result is None:
            return None

        return self.signal_result.signal

    @property
    def created(
        self,
    ) -> bool:
        return (
            self.reason
            is TradingDaySignalRuntimeReason.CREATED
        )


class TradingDaySignalRuntimeCoordinator:
    """
    Routes one T09 LevelEvent into the existing M04 SignalEngine.

    The two supplied SelectedOption instances are the fixed
    morning contracts chosen by M10.

    They are never replaced or re-selected in this coordinator.
    """

    def __init__(
        self,
        *,
        entry_gate:
            TradingDayEntryGateCoordinator,
        signal_engine: SignalEngine,
        selected_call: SelectedOption,
        selected_put: SelectedOption,
    ) -> None:
        self._entry_gate = entry_gate
        self._signal_engine = signal_engine

        self._selected_call = selected_call
        self._selected_put = selected_put

        self._validate_selected_pair()

    @property
    def entry_gate(
        self,
    ) -> TradingDayEntryGateCoordinator:
        return self._entry_gate

    @property
    def signal_engine(
        self,
    ) -> SignalEngine:
        """
        Return the exact M04 SignalEngine owned by this
        application runtime boundary.

        T14 entry lifecycle composition must use this same
        instance when marking a proven trade OPEN or releasing
        an accepted signal that never became a trade.
        """

        return self._signal_engine

    @property
    def selected_call(
        self,
    ) -> SelectedOption:
        return self._selected_call

    @property
    def selected_put(
        self,
    ) -> SelectedOption:
        return self._selected_put

    def process_event(
        self,
        event: LevelEvent,
    ) -> TradingDaySignalRuntimeResult:
        """
        Process one LevelEvent.

        Routine events for non-selected contracts are ignored
        without touching the runtime gate or M04 state.
        """

        if not isinstance(
            event,
            LevelEvent,
        ):
            raise TypeError(
                "event must be a LevelEvent"
            )

        resolved = (
            self._resolve_selected_contract(
                event
            )
        )

        if resolved is None:
            return TradingDaySignalRuntimeResult(
                event=event,
                reason=(
                    TradingDaySignalRuntimeReason
                    .UNSELECTED_CONTRACT
                ),
                selected_option=None,
                direction=None,
                entry_gate_decision=None,
                signal_result=None,
            )

        selected_option, direction = (
            resolved
        )

        # ----------------------------------------------------
        # Global entry permission BEFORE M04.
        #
        # SignalEngine.process() acquires a contract+level lock
        # when it creates a signal. Therefore scheduler/runtime
        # denial must occur before invoking M04.
        # ----------------------------------------------------

        gate_decision = (
            self._entry_gate.evaluate(
                evaluated_at=event.timestamp
            )
        )

        if not gate_decision.allowed:
            return TradingDaySignalRuntimeResult(
                event=event,
                reason=(
                    TradingDaySignalRuntimeReason
                    .ENTRY_GATE_BLOCKED
                ),
                selected_option=selected_option,
                direction=direction,
                entry_gate_decision=(
                    gate_decision
                ),
                signal_result=None,
            )

        # ----------------------------------------------------
        # Translate successful M10/M08 orchestration permission
        # into M04's existing eligibility context.
        #
        # M04 still independently enforces:
        #   - event trading date
        #   - 09:21 start
        #   - 15:15 end
        #   - K5/K6/K7 only
        #   - duplicate suppression
        #   - level lock
        #   - re-entry state
        # ----------------------------------------------------

        context = EligibilityContext(
            trading_date=(
                self._entry_gate
                .scheduler
                .trading_date
            ),
            session_state=(
                StrategySessionState.MONITORING
            ),
            trading_enabled=True,
            platform_halted=False,
        )

        signal_result = (
            self._signal_engine.process(
                event=event,
                direction=direction,
                context=context,
            )
        )

        if not signal_result.accepted:
            return TradingDaySignalRuntimeResult(
                event=event,
                reason=(
                    TradingDaySignalRuntimeReason
                    .SIGNAL_REJECTED
                ),
                selected_option=selected_option,
                direction=direction,
                entry_gate_decision=(
                    gate_decision
                ),
                signal_result=signal_result,
            )

        signal = signal_result.signal

        assert signal is not None

        # ----------------------------------------------------
        # Contract compatibility must survive M04 unchanged.
        # ----------------------------------------------------

        if (
            signal.instrument_security_id
            != selected_option.security_id
        ):
            raise TradingDaySignalRuntimeError(
                "M04 signal security ID does not match "
                "fixed selected option"
            )

        if (
            signal.instrument_symbol
            != selected_option.symbol
        ):
            raise TradingDaySignalRuntimeError(
                "M04 signal symbol does not match "
                "fixed selected option"
            )

        if signal.direction is not direction:
            raise TradingDaySignalRuntimeError(
                "M04 signal direction does not match "
                "fixed selected option"
            )

        return TradingDaySignalRuntimeResult(
            event=event,
            reason=(
                TradingDaySignalRuntimeReason.CREATED
            ),
            selected_option=selected_option,
            direction=direction,
            entry_gate_decision=gate_decision,
            signal_result=signal_result,
        )

    def _resolve_selected_contract(
        self,
        event: LevelEvent,
    ) -> tuple[
        SelectedOption,
        SignalDirection,
    ] | None:
        if (
            event.instrument_security_id
            == self._selected_call.security_id
        ):
            if (
                event.instrument_symbol
                != self._selected_call.symbol
            ):
                raise TradingDaySignalRuntimeError(
                    "CALL event symbol does not match "
                    "fixed selected CALL"
                )

            return (
                self._selected_call,
                SignalDirection.CALL,
            )

        if (
            event.instrument_security_id
            == self._selected_put.security_id
        ):
            if (
                event.instrument_symbol
                != self._selected_put.symbol
            ):
                raise TradingDaySignalRuntimeError(
                    "PUT event symbol does not match "
                    "fixed selected PUT"
                )

            return (
                self._selected_put,
                SignalDirection.PUT,
            )

        return None

    def _validate_selected_pair(
        self,
    ) -> None:
        if (
            self._selected_call.option_type
            is not OptionType.CALL
        ):
            raise ValueError(
                "selected_call must be CALL"
            )

        if (
            self._selected_put.option_type
            is not OptionType.PUT
        ):
            raise ValueError(
                "selected_put must be PUT"
            )

        if (
            self._selected_call.security_id
            == self._selected_put.security_id
        ):
            raise ValueError(
                "selected CALL and PUT must have "
                "different security IDs"
            )

        if (
            self._selected_call.expiry
            != self._selected_put.expiry
        ):
            raise ValueError(
                "selected CALL and PUT must have "
                "the same expiry"
            )

        if (
            self._selected_call
            .contract
            .underlying_symbol
            != self._selected_put
            .contract
            .underlying_symbol
        ):
            raise ValueError(
                "selected CALL and PUT must have "
                "the same underlying"
            )


__all__ = [
    "TradingDaySignalRuntimeCoordinator",
    "TradingDaySignalRuntimeError",
    "TradingDaySignalRuntimeReason",
    "TradingDaySignalRuntimeResult",
]
