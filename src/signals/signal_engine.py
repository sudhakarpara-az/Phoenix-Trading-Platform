"""
Phoenix Signal Engine.

Coordinates signal eligibility, duplicate suppression,
level locking, re-entry classification, and TradingSignal creation.

No broker execution or option-chain selection belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock

from src.signals.duplicate_signal_guard import DuplicateSignalGuard
from src.signals.eligibility_policy import (
    EligibilityContext,
    EligibilityReason,
    SignalEligibilityPolicy,
)
from src.signals.level_lock_manager import LevelLockManager
from src.signals.reentry_state_manager import ReentryStateManager
from src.signals.signal_builder import (
    SignalBuilder,
    SignalBuildRequest,
)
from src.signals.signal_types import (
    SignalDirection,
    TradingSignal,
)
from src.strategy.strategy_types import (
    EntryLevel,
    LevelEvent,
)


class SignalEngineReason(str, Enum):
    CREATED = "CREATED"

    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    DUPLICATE = "DUPLICATE"
    LEVEL_LOCKED = "LEVEL_LOCKED"
    REENTRY_BLOCKED = "REENTRY_BLOCKED"


@dataclass(frozen=True, slots=True)
class SignalEngineResult:
    """
    Outcome from processing one signal candidate.
    """

    accepted: bool
    reason: SignalEngineReason

    signal: TradingSignal | None = None
    eligibility_reason: EligibilityReason | None = None

    def __post_init__(self) -> None:
        if self.accepted and self.signal is None:
            raise ValueError(
                "accepted result must contain a signal"
            )

        if not self.accepted and self.signal is not None:
            raise ValueError(
                "rejected result cannot contain a signal"
            )


class SignalEngine:
    """
    Main M04 signal-generation orchestrator.

    Processing order:

        1. Eligibility
        2. Duplicate suppression
        3. Level-lock check
        4. Re-entry-state check
        5. Build TradingSignal
        6. Acquire level lock

    The actual trade is marked ACTIVE later when execution
    confirms that a position/order lifecycle has started.
    """

    def __init__(
        self,
        eligibility_policy: SignalEligibilityPolicy,
        duplicate_guard: DuplicateSignalGuard,
        level_lock_manager: LevelLockManager,
        reentry_manager: ReentryStateManager,
        signal_builder: SignalBuilder,
        underlying_symbol: str = "NIFTY 50",
        underlying_security_id: str = "13",
    ) -> None:
        if not underlying_symbol.strip():
            raise ValueError(
                "underlying_symbol cannot be empty"
            )

        if not underlying_security_id.strip():
            raise ValueError(
                "underlying_security_id cannot be empty"
            )

        self._eligibility_policy = eligibility_policy
        self._duplicate_guard = duplicate_guard
        self._level_locks = level_lock_manager
        self._reentry_manager = reentry_manager
        self._signal_builder = signal_builder

        self._underlying_symbol = (
            underlying_symbol.strip()
        )

        self._underlying_security_id = (
            underlying_security_id.strip()
        )

        self._lock = RLock()

    def process(
        self,
        event: LevelEvent,
        direction: SignalDirection,
        context: EligibilityContext,
    ) -> SignalEngineResult:
        """
        Process one LevelEvent into a TradingSignal candidate.
        """

        with self._lock:
            eligibility = self._eligibility_policy.evaluate(
                event=event,
                context=context,
            )

            if not eligibility.eligible:
                return SignalEngineResult(
                    accepted=False,
                    reason=SignalEngineReason.NOT_ELIGIBLE,
                    eligibility_reason=eligibility.reason,
                )

            if not self._duplicate_guard.allow(event):
                return SignalEngineResult(
                    accepted=False,
                    reason=SignalEngineReason.DUPLICATE,
                )

            entry_level = self._to_entry_level(
                event
            )

            if self._level_locks.is_locked(
                entry_level
            ):
                return SignalEngineResult(
                    accepted=False,
                    reason=SignalEngineReason.LEVEL_LOCKED,
                )

            if not self._reentry_manager.can_enter(
                entry_level
            ):
                return SignalEngineResult(
                    accepted=False,
                    reason=SignalEngineReason.REENTRY_BLOCKED,
                )

            is_reentry = (
                self._reentry_manager.is_reentry(
                    entry_level
                )
            )

            signal = self._signal_builder.build(
                SignalBuildRequest(
                    event=event,
                    direction=direction,
                    underlying_symbol=(
                        self._underlying_symbol
                    ),
                    underlying_security_id=(
                        self._underlying_security_id
                    ),
                    is_reentry=is_reentry,
                )
            )

            acquired = self._level_locks.acquire(
                level=entry_level,
                trading_date=event.trading_date,
                locked_at=event.timestamp,
                reference_id=signal.signal_id.value,
            )

            if not acquired:
                return SignalEngineResult(
                    accepted=False,
                    reason=SignalEngineReason.LEVEL_LOCKED,
                )

            return SignalEngineResult(
                accepted=True,
                reason=SignalEngineReason.CREATED,
                signal=signal,
            )

    def mark_trade_open(
        self,
        signal: TradingSignal,
    ) -> None:
        """
        Mark execution of an accepted signal as ACTIVE.

        This should be called later by the execution lifecycle
        after the trade has actually entered/opened.
        """

        with self._lock:
            self._reentry_manager.mark_open(
                level=signal.level,
                trading_date=signal.trading_date,
                opened_at=signal.generated_at,
            )

    def mark_trade_closed(
        self,
        level: EntryLevel,
        closed_at,
    ) -> None:
        """
        Mark a level trade closed and make the level
        eligible for future re-entry.
        """

        with self._lock:
            self._reentry_manager.mark_closed(
                level=level,
                closed_at=closed_at,
            )

            self._level_locks.release(level)

            from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    LevelEvent,
)

            self._duplicate_guard.clear_level(
    KSLevelName(level.value)
)

    def release_signal_lock(
        self,
        signal: TradingSignal,
    ) -> bool:
        """
        Release a lock when an accepted signal never becomes
        an active trade, e.g. later rejection/cancellation.
        """

        with self._lock:
            return self._level_locks.release(
                signal.level
            )

    @staticmethod
    def _to_entry_level(
        event: LevelEvent,
    ) -> EntryLevel:
        try:
            return EntryLevel(
                event.level.value
            )

        except ValueError as exc:
            raise ValueError(
                f"{event.level.value} is not a valid entry level"
            ) from exc