"""
Order
"""

from dataclasses import dataclass

from src.domain.enums import OrderStatus


@dataclass(slots=True)
class Order:

    order_id: str

    broker_order_id: str | None

    status: OrderStatus