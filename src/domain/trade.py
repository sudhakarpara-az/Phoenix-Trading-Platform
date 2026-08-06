"""
Trade
"""

from dataclasses import dataclass
from datetime import datetime

from src.domain.enums import TradeStatus


@dataclass(slots=True)
class Trade:

    trade_id: str

    entry_time: datetime

    exit_time: datetime | None

    pnl: float

    status: TradeStatus