"""
Order Request
"""

from dataclasses import dataclass

from src.domain.enums import OrderType
from src.domain.enums import OptionSide


@dataclass(slots=True)
class OrderRequest:

    symbol: str

    side: OptionSide

    quantity: int

    order_type: OrderType

    price: float