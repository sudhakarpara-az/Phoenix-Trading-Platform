"""
KS Level Event
"""

from dataclasses import dataclass
from datetime import datetime

from src.domain.enums import KSLevel


@dataclass(slots=True)
class LevelEvent:
    level: KSLevel
    underlying_price: float
    timestamp: datetime