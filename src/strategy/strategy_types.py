"""
KS Phoenix strategy domain models.

These models represent the broker-independent strategy state
used throughout the Phoenix Trading Platform.

No Dhan, option-selection, order, or execution-specific logic
belongs in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class KSLevelName(str, Enum):
    """Supported KS Phoenix levels."""

    K0 = "K0"
    K1 = "K1"
    K2 = "K2"
    K3 = "K3"
    K5 = "K5"
    K6 = "K6"
    K7 = "K7"


class EntryLevel(str, Enum):
    """
    KS levels currently eligible for strategy entries.

    Keeping this separate from KSLevelName prevents future code
    from accidentally treating every calculated level as an entry.
    """

    K5 = "K5"
    K6 = "K6"
    K7 = "K7"


class StrategySessionState(str, Enum):
    """Lifecycle state of the daily KS Phoenix strategy session."""

    WAITING_FOR_MARKET = "WAITING_FOR_MARKET"
    BUILDING_REFERENCE_CANDLE = "BUILDING_REFERENCE_CANDLE"
    LEVELS_READY = "LEVELS_READY"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


class LevelEventType(str, Enum):
    """
    Type of KS level interaction detected from NIFTY.

    Additional event types can be added later without modifying
    the market-data domain.
    """

    TOUCHED = "TOUCHED"
    CROSSED_UP = "CROSSED_UP"
    CROSSED_DOWN = "CROSSED_DOWN"


@dataclass(frozen=True, slots=True)
class ReferenceCandle:
    """
    Completed NIFTY 09:15–09:20 reference candle.

    This candle becomes immutable after 09:20 and is the source
    for the day's KS Phoenix calculations.
    """

    trading_date: date

    instrument_security_id: str
    instrument_symbol: str

    start_time: datetime
    end_time: datetime

    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )

        if not self.instrument_symbol.strip():
            raise ValueError(
                "instrument_symbol cannot be empty"
            )
        prices = {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }

        for name, value in prices.items():
            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )

        if self.high < self.low:
            raise ValueError(
                "high cannot be lower than low"
            )

        if self.high < self.open:
            raise ValueError(
                "high cannot be lower than open"
            )

        if self.high < self.close:
            raise ValueError(
                "high cannot be lower than close"
            )

        if self.low > self.open:
            raise ValueError(
                "low cannot be greater than open"
            )

        if self.low > self.close:
            raise ValueError(
                "low cannot be greater than close"
            )

        if self.end_time <= self.start_time:
            raise ValueError(
                "end_time must be after start_time"
            )

        if self.start_time.date() != self.trading_date:
            raise ValueError(
                "start_time must match trading_date"
            )

        if self.end_time.date() != self.trading_date:
            raise ValueError(
                "end_time must match trading_date"
            )


@dataclass(frozen=True, slots=True)
class KSBaseLevels:
    """
    Intermediate KS Phoenix values derived from the
    completed reference candle.

    These values correspond to:
        N1
        N2
        C1
        E
        T

    K0-K7 calculations are deliberately kept separate.
    """

    trading_date: date

    instrument_security_id: str
    instrument_symbol: str

    n1: float
    n2: float
    c1: float

    e_level: float
    t_level: float

    calculated_at: datetime

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )

        if not self.instrument_symbol.strip():
            raise ValueError(
                "instrument_symbol cannot be empty"
            )
        values = {
            "n1": self.n1,
            "n2": self.n2,
            "c1": self.c1,
            "e_level": self.e_level,
            "t_level": self.t_level,
        }

        for name, value in values.items():
            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )


@dataclass(frozen=True, slots=True)
class KSLevels:
    """
    Complete daily KS Phoenix level set.

    Includes both the intermediate N/E/T calculations
    and the final K-level values.
    """

    trading_date: date

    instrument_security_id: str
    instrument_symbol: str

    high_915: float
    low_915: float
    close_915: float

    n1: float
    n2: float
    c1: float

    e_level: float
    t_level: float

    k0: float
    k1: float
    k2: float
    k3: float
    k5: float
    k6: float
    k7: float

    calculated_at: datetime
    formula_version: str = "KS_PHOENIX_V1"

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )

        if not self.instrument_symbol.strip():
            raise ValueError(
                "instrument_symbol cannot be empty"
            )

        numeric_values = {
            "high_915": self.high_915,
            "low_915": self.low_915,
            "close_915": self.close_915,
            "n1": self.n1,
            "n2": self.n2,
            "c1": self.c1,
            "e_level": self.e_level,
            "t_level": self.t_level,
            "k0": self.k0,
            "k1": self.k1,
            "k2": self.k2,
            "k3": self.k3,
            "k5": self.k5,
            "k6": self.k6,
            "k7": self.k7,
        }

        for name, value in numeric_values.items():
            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )

        if self.high_915 < self.low_915:
            raise ValueError(
                "high_915 cannot be lower than low_915"
            )

        if not self.formula_version.strip():
            raise ValueError(
                "formula_version cannot be empty"
            )

    def get(self, level: KSLevelName) -> float:
        """Return the price corresponding to one KS level."""

        mapping = {
            KSLevelName.K0: self.k0,
            KSLevelName.K1: self.k1,
            KSLevelName.K2: self.k2,
            KSLevelName.K3: self.k3,
            KSLevelName.K5: self.k5,
            KSLevelName.K6: self.k6,
            KSLevelName.K7: self.k7,
        }

        return mapping[level]

    def entry_level_price(
        self,
        level: EntryLevel,
    ) -> float:
        """Return the configured entry-level price."""

        mapping = {
            EntryLevel.K5: self.k5,
            EntryLevel.K6: self.k6,
            EntryLevel.K7: self.k7,
        }

        return mapping[level]

    def target_for(
        self,
        entry_level: EntryLevel,
    ) -> KSLevelName:
        """
        Return the finalized KS target mapping.

        K5 -> K3
        K6 -> K5
        K7 -> K6
        """

        mapping = {
            EntryLevel.K5: KSLevelName.K3,
            EntryLevel.K6: KSLevelName.K5,
            EntryLevel.K7: KSLevelName.K6,
        }

        return mapping[entry_level]


@dataclass(frozen=True, slots=True)
class LevelEvent:
    """
    Represents a NIFTY interaction with one KS level.

    This is a strategy-level event only. It is not yet a
    trading signal or broker order.
    """

    trading_date: date

    instrument_security_id: str
    instrument_symbol: str

    level: KSLevelName
    event_type: LevelEventType

    level_price: float
    market_price: float

    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.instrument_security_id.strip():
            raise ValueError(
                "instrument_security_id cannot be empty"
            )

        if not self.instrument_symbol.strip():
            raise ValueError(
                "instrument_symbol cannot be empty"
            )
        if self.level_price <= 0:
            raise ValueError(
                "level_price must be greater than zero"
            )

        if self.market_price <= 0:
            raise ValueError(
                "market_price must be greater than zero"
            )