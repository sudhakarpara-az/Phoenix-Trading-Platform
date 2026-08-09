"""
Broker-independent historical candle models.

This module contains normalized candle data used by Phoenix
without exposing broker-specific response structures.

It deliberately contains no strategy calculations,
option-selection logic, or broker SDK calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class HistoricalCandle:
    """
    One completed broker-independent historical candle.

    Instrument identity is preserved explicitly so downstream
    strategy coordination can prove that candle ownership
    matches the selected option contract.
    """

    security_id: str
    symbol: str

    start_time: datetime
    end_time: datetime

    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError(
                "security_id cannot be empty"
            )

        if not self.symbol.strip():
            raise ValueError(
                "symbol cannot be empty"
            )

        if type(self.start_time) is not datetime:
            raise TypeError(
                "start_time must be a datetime"
            )

        if type(self.end_time) is not datetime:
            raise TypeError(
                "end_time must be a datetime"
            )

        if self.end_time <= self.start_time:
            raise ValueError(
                "end_time must be after start_time"
            )

        values = {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }

        for name, value in values.items():
            if (
                isinstance(value, bool)
                or not isinstance(
                    value,
                    (int, float),
                )
                or not isfinite(value)
                or value <= 0
            ):
                raise ValueError(
                    f"{name} must be a finite number "
                    "greater than zero"
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
