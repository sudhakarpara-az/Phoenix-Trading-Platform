"""
Signal eligibility policy for Phoenix Trading Platform.

Determines whether a KS Phoenix LevelEvent is permitted
to proceed toward signal generation.

This module does not create signals, lock levels,
manage positions, or place broker orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum

from src.strategy.strategy_types import (
    EntryLevel,
    LevelEvent,
    StrategySessionState,
)


class EligibilityReason(str, Enum):
    """
    Reason for allowing or rejecting a signal candidate.
    """

    ELIGIBLE = "ELIGIBLE"

    INVALID_LEVEL = "INVALID_LEVEL"
    WRONG_TRADING_DATE = "WRONG_TRADING_DATE"

    BEFORE_TRADING_WINDOW = "BEFORE_TRADING_WINDOW"
    AFTER_TRADING_WINDOW = "AFTER_TRADING_WINDOW"

    STRATEGY_NOT_MONITORING = "STRATEGY_NOT_MONITORING"

    TRADING_DISABLED = "TRADING_DISABLED"
    PLATFORM_HALTED = "PLATFORM_HALTED"


@dataclass(frozen=True, slots=True)
class EligibilityContext:
    """
    Runtime context used to evaluate one LevelEvent.
    """

    trading_date: date
    session_state: StrategySessionState

    trading_enabled: bool = True
    platform_halted: bool = False


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """
    Result of evaluating one signal candidate.
    """

    eligible: bool
    reason: EligibilityReason

    def __post_init__(self) -> None:
        if self.eligible:
            if self.reason is not EligibilityReason.ELIGIBLE:
                raise ValueError(
                    "eligible decision must use ELIGIBLE reason"
                )

        else:
            if self.reason is EligibilityReason.ELIGIBLE:
                raise ValueError(
                    "rejected decision cannot use ELIGIBLE reason"
                )


class SignalEligibilityPolicy:
    """
    Applies Phoenix trading rules before signal generation.

    Current rules:
        - Only K5/K6/K7 are valid entry levels.
        - Trading begins at 09:21 after the 09:20 candle closes.
        - No new signals at or after 15:15.
        - Strategy session must be MONITORING.
        - Trading must be enabled.
        - Platform must not be halted.
        - Event date must match active trading date.
    """

    def __init__(
        self,
        trading_start: time = time(9, 21),
        trading_end: time = time(15, 15),
    ) -> None:
        if trading_end <= trading_start:
            raise ValueError(
                "trading_end must be after trading_start"
            )

        self._trading_start = trading_start
        self._trading_end = trading_end

    @property
    def trading_start(self) -> time:
        return self._trading_start

    @property
    def trading_end(self) -> time:
        return self._trading_end

    def evaluate(
        self,
        event: LevelEvent,
        context: EligibilityContext,
    ) -> EligibilityDecision:
        """
        Evaluate whether a LevelEvent may proceed
        toward signal generation.
        """

        if event.trading_date != context.trading_date:
            return self._reject(
                EligibilityReason.WRONG_TRADING_DATE
            )

        if not self._is_entry_level(event):
            return self._reject(
                EligibilityReason.INVALID_LEVEL
            )

        event_time = event.timestamp.time()

        if event_time < self._trading_start:
            return self._reject(
                EligibilityReason.BEFORE_TRADING_WINDOW
            )

        if event_time >= self._trading_end:
            return self._reject(
                EligibilityReason.AFTER_TRADING_WINDOW
            )

        if (
            context.session_state
            is not StrategySessionState.MONITORING
        ):
            return self._reject(
                EligibilityReason.STRATEGY_NOT_MONITORING
            )

        if not context.trading_enabled:
            return self._reject(
                EligibilityReason.TRADING_DISABLED
            )

        if context.platform_halted:
            return self._reject(
                EligibilityReason.PLATFORM_HALTED
            )

        return EligibilityDecision(
            eligible=True,
            reason=EligibilityReason.ELIGIBLE,
        )

    @staticmethod
    def _is_entry_level(
        event: LevelEvent,
    ) -> bool:
        """
        Return True only for K5/K6/K7.
        """

        return event.level.value in {
            EntryLevel.K5.value,
            EntryLevel.K6.value,
            EntryLevel.K7.value,
        }

    @staticmethod
    def _reject(
        reason: EligibilityReason,
    ) -> EligibilityDecision:
        return EligibilityDecision(
            eligible=False,
            reason=reason,
        )
