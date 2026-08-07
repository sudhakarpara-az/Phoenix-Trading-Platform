"""
TradingSignal construction for Phoenix Trading Platform.

Builds immutable broker-independent TradingSignal objects
from approved KS Phoenix LevelEvent inputs.

This module does not perform eligibility checks,
locking, duplicate suppression, option selection,
or broker execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import count
from threading import RLock

from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    LevelEvent,
    LevelEventType,
)


@dataclass(frozen=True, slots=True)
class SignalBuildRequest:
    """
    Input required to build one TradingSignal.
    """

    event: LevelEvent
    direction: SignalDirection

    underlying_symbol: str
    underlying_security_id: str

    is_reentry: bool = False


class SignalBuilder:
    """
    Constructs Phoenix TradingSignal objects.

    Responsibilities:
        - Convert KS level to EntryLevel.
        - Map LevelEventType to SignalReason.
        - Generate stable session-local signal IDs.
        - Preserve strategy metadata.
    """

    def __init__(
        self,
        strategy_version: str = "KS_PHOENIX_V1",
    ) -> None:
        normalized_version = strategy_version.strip()

        if not normalized_version:
            raise ValueError(
                "strategy_version cannot be empty"
            )

        self._strategy_version = normalized_version
        self._sequence = count(1)
        self._lock = RLock()

    @property
    def strategy_version(self) -> str:
        return self._strategy_version

    def build(
        self,
        request: SignalBuildRequest,
    ) -> TradingSignal:
        """
        Build one immutable TradingSignal.
        """

        entry_level = self._to_entry_level(
            request.event.level
        )

        reason = self._to_signal_reason(
            event_type=request.event.event_type,
            is_reentry=request.is_reentry,
        )

        signal_id = self._next_signal_id(
            event=request.event,
            entry_level=entry_level,
        )

        return TradingSignal(
            signal_id=SignalId(signal_id),
            trading_date=request.event.trading_date,
            level=entry_level,
            direction=request.direction,
            underlying_symbol=request.underlying_symbol,
            underlying_security_id=(
                request.underlying_security_id
            ),
            underlying_price=request.event.market_price,
            level_price=request.event.level_price,
            reason=reason,
            state=SignalState.CREATED,
            generated_at=request.event.timestamp,
            is_reentry=request.is_reentry,
            strategy_version=self._strategy_version,
        )

    def _next_signal_id(
        self,
        event: LevelEvent,
        entry_level: EntryLevel,
    ) -> str:
        """
        Generate one deterministic session-local signal ID.

        Format:
            SIG-YYYYMMDD-K5-000001
        """

        with self._lock:
            sequence = next(self._sequence)

        trading_date = event.trading_date.strftime(
            "%Y%m%d"
        )

        return (
            f"SIG-"
            f"{trading_date}-"
            f"{entry_level.value}-"
            f"{sequence:06d}"
        )

    @staticmethod
    def _to_entry_level(
        level: KSLevelName,
    ) -> EntryLevel:
        """
        Convert K5/K6/K7 into EntryLevel.

        Other KS levels are not valid signal-entry levels.
        """

        try:
            return EntryLevel(level.value)

        except ValueError as exc:
            raise ValueError(
                f"{level.value} is not a valid entry level"
            ) from exc

    @staticmethod
    def _to_signal_reason(
        event_type: LevelEventType,
        is_reentry: bool,
    ) -> SignalReason:
        """
        Convert LevelEventType to SignalReason.
        """

        if is_reentry:
            return SignalReason.REENTRY

        mapping = {
            LevelEventType.TOUCHED: (
                SignalReason.LEVEL_TOUCH
            ),
            LevelEventType.CROSSED_UP: (
                SignalReason.CROSS_UP
            ),
            LevelEventType.CROSSED_DOWN: (
                SignalReason.CROSS_DOWN
            ),
        }

        return mapping[event_type]