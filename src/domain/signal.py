"""
Trading Signal
"""

from dataclasses import dataclass
from datetime import datetime

from src.domain.enums import KSLevel
from src.domain.enums import OptionSide


@dataclass(slots=True)
class Signal:

    signal_id: str

    timestamp: datetime

    level: KSLevel

    side: OptionSide

    strike: int

    delta: float

    option_price: float

    quantity: int