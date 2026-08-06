"""
Market domain models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    MCX = "MCX"


class TickType(str, Enum):
    LTP = "LTP"
    QUOTE = "QUOTE"
    FULL = "FULL"


@dataclass(slots=True)
class MarketTick:
    """
    Represents one market update.
    """

    exchange: Exchange
    symbol: str
    security_id: str

    ltp: float
    volume: int

    timestamp: datetime


@dataclass(slots=True)
class Instrument:
    """
    Tradable instrument.
    """

    exchange: Exchange
    symbol: str
    security_id: str