"""
Broker-independent market domain models.

These models are shared by the market-data, strategy,
option-selection, execution, portfolio, and dashboard layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Exchange(str, Enum):
    """Supported exchange segments."""

    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    MCX = "MCX"


class TickType(str, Enum):
    """Supported market-feed subscription modes."""

    LTP = "LTP"
    QUOTE = "QUOTE"
    FULL = "FULL"


@dataclass(frozen=True, slots=True)
class Instrument:
    """Represents a broker-independent market instrument."""

    exchange: Exchange
    symbol: str
    security_id: str

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")

        if not self.security_id.strip():
            raise ValueError("security_id cannot be empty")


@dataclass(frozen=True, slots=True)
class MarketTick:
    """Represents one normalized live market-price update."""

    exchange: Exchange
    symbol: str
    security_id: str
    ltp: float
    volume: int
    timestamp: datetime
    tick_type: TickType = TickType.LTP

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")

        if not self.security_id.strip():
            raise ValueError("security_id cannot be empty")

        if self.ltp <= 0:
            raise ValueError("ltp must be greater than zero")

        if self.volume < 0:
            raise ValueError("volume cannot be negative")