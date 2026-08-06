from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class MarketTick:
    symbol: str
    exchange: str
    ltp: float
    volume: int
    timestamp: datetime