"""
Phoenix trading-signal domain models.

These models represent trading intent generated from
KS Phoenix strategy events.

No broker-specific, option-chain, or execution logic
belongs in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from src.strategy.strategy_types import EntryLevel


class SignalDirection(str, Enum):
    """
    Directional option-buying intent.
    """

    CALL = "CALL"
    PUT = "PUT"


class SignalState(str, Enum):
    """
    Lifecycle state of one generated trading signal.
    """

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class SignalReason(str, Enum):
    """
    Reason a trading signal was generated.
    """

    LEVEL_TOUCH = "LEVEL_TOUCH"
    CROSS_UP = "CROSS_UP"
    CROSS_DOWN = "CROSS_DOWN"
    REENTRY = "REENTRY"


@dataclass(frozen=True, slots=True)
class SignalId:
    """
    Stable signal identifier.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError(
                "signal id cannot be empty"
            )


@dataclass(frozen=True, slots=True)
class TradingSignal:
    """
    Broker-independent KS Phoenix trading signal.

    Option selection and execution happen in later modules.
    """

    signal_id: SignalId

    trading_date: date

    level: EntryLevel
    direction: SignalDirection

    underlying_symbol: str
    underlying_security_id: str
    underlying_price: float

    level_price: float

    reason: SignalReason
    state: SignalState

    generated_at: datetime

    is_reentry: bool = False

    strategy_version: str = "KS_PHOENIX_V1"

    def __post_init__(self) -> None:
        if not self.underlying_symbol.strip():
            raise ValueError(
                "underlying_symbol cannot be empty"
            )

        if not self.underlying_security_id.strip():
            raise ValueError(
                "underlying_security_id cannot be empty"
            )

        if self.underlying_price <= 0:
            raise ValueError(
                "underlying_price must be greater than zero"
            )

        if self.level_price <= 0:
            raise ValueError(
                "level_price must be greater than zero"
            )

        if not self.strategy_version.strip():
            raise ValueError(
                "strategy_version cannot be empty"
            )