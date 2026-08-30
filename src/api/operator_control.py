"""
Transport-neutral M13 operator control facade.

M13 does not own trading-control state, BUY cancellation,
SELL liquidation, broker access, persistence, or flatness
evaluation. It delegates those responsibilities to the exact
M10 TradingControlCommandService and projects only safe,
operator-facing result data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.app.trading_control import (
    ExitAndStopCommandResult,
    TradingControlSnapshot,
    TradingControlState,
)


class OperatorControlCommandPort(
    Protocol,
):
    """
    Narrow M10 command contract consumed by M13.
    """

    def exit_and_stop(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> ExitAndStopCommandResult:
        ...

    def resume(
        self,
        *,
        changed_at: datetime,
        message: str | None = None,
    ) -> TradingControlSnapshot:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorControlStateView:
    """
    Safe operator projection of durable trading-control state.
    """

    state: str
    changed_at: datetime | None
    new_entries_allowed: bool


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorExitAndStopView:
    """
    Safe M13 projection of one complete EXIT AND STOP request.

    Internal BUY/SELL result objects are intentionally not
    exposed. M13 returns counts and sanitized phase status only.
    """

    control: OperatorControlStateView

    requested_at: datetime

    flat_confirmed: bool
    requires_attention: bool

    pending_entry_result_count: int
    liquidation_result_count: int

    open_position_count: int | None
    unresolved_order_count: int | None

    entry_error: str | None
    liquidation_error: str | None
    readiness_error: str | None

    def __post_init__(
        self,
    ) -> None:
        if self.pending_entry_result_count < 0:
            raise ValueError(
                "pending_entry_result_count cannot be negative"
            )

        if self.liquidation_result_count < 0:
            raise ValueError(
                "liquidation_result_count cannot be negative"
            )

        if (
            self.open_position_count is not None
            and self.open_position_count < 0
        ):
            raise ValueError(
                "open_position_count cannot be negative"
            )

        if (
            self.unresolved_order_count is not None
            and self.unresolved_order_count < 0
        ):
            raise ValueError(
                "unresolved_order_count cannot be negative"
            )


class OperatorControlService:
    """
    M13 command-facing facade over the exact M10 strong-stop
    command owner.

    Responsibilities are intentionally narrow:

        validate operator-facing inputs
        delegate exactly once to M10
        project safe immutable result views

    It performs no direct broker, repository, position-registry,
    BUY-cancellation, SELL-liquidation, or risk-state operation.
    """

    def __init__(
        self,
        *,
        commands: OperatorControlCommandPort,
    ) -> None:
        self._commands = commands

    @property
    def commands(
        self,
    ) -> OperatorControlCommandPort:
        return self._commands

    def exit_and_stop(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> OperatorExitAndStopView:
        self._validate_datetime(
            requested_at,
            name="requested_at",
        )

        self._validate_message(
            message
        )

        result = (
            self._commands
            .exit_and_stop(
                changed_at=requested_at,
                message=message,
            )
        )

        if not isinstance(
            result,
            ExitAndStopCommandResult,
        ):
            raise TypeError(
                "operator control command returned invalid "
                "EXIT AND STOP result"
            )

        readiness = result.readiness

        return OperatorExitAndStopView(
            control=(
                self._map_control(
                    result.control
                )
            ),
            requested_at=(
                result.requested_at
            ),
            flat_confirmed=(
                result.flat_confirmed
            ),
            requires_attention=(
                result.requires_attention
            ),
            pending_entry_result_count=len(
                result.entry_results
            ),
            liquidation_result_count=len(
                result.liquidation_results
            ),
            open_position_count=(
                None
                if readiness is None
                else readiness.open_position_count
            ),
            unresolved_order_count=(
                None
                if readiness is None
                else readiness.unresolved_order_count
            ),
            entry_error=(
                result.entry_error
            ),
            liquidation_error=(
                result.liquidation_error
            ),
            readiness_error=(
                result.readiness_error
            ),
        )

    def resume(
        self,
        *,
        requested_at: datetime,
        message: str | None = None,
    ) -> OperatorControlStateView:
        self._validate_datetime(
            requested_at,
            name="requested_at",
        )

        self._validate_message(
            message
        )

        snapshot = (
            self._commands
            .resume(
                changed_at=requested_at,
                message=message,
            )
        )

        if not isinstance(
            snapshot,
            TradingControlSnapshot,
        ):
            raise TypeError(
                "operator control command returned invalid "
                "RESUME result"
            )

        return self._map_control(
            snapshot
        )

    @staticmethod
    def _map_control(
        snapshot: TradingControlSnapshot,
    ) -> OperatorControlStateView:
        return OperatorControlStateView(
            state=snapshot.state.value,
            changed_at=snapshot.changed_at,
            new_entries_allowed=(
                snapshot.state
                is TradingControlState.ACTIVE
            ),
        )

    @staticmethod
    def _validate_datetime(
        value: datetime,
        *,
        name: str,
    ) -> None:
        if type(value) is not datetime:
            raise TypeError(
                f"{name} must be datetime"
            )

    @staticmethod
    def _validate_message(
        value: str | None,
    ) -> None:
        if (
            value is not None
            and not isinstance(
                value,
                str,
            )
        ):
            raise TypeError(
                "message must be str or None"
            )


__all__ = [
    "OperatorControlCommandPort",
    "OperatorControlService",
    "OperatorControlStateView",
    "OperatorExitAndStopView",
]
