"""
Position
"""

from dataclasses import dataclass

from src.domain.enums import KSLevel
from src.domain.enums import OptionSide


@dataclass(slots=True)
class Position:

    trade_id: str

    level: KSLevel

    side: OptionSide

    strike: int

    quantity: int

    entry_price: float

    stop_loss: float

    target: float

    is_open: bool = True