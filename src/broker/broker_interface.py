"""
Broker Interface

Defines the contract for all broker implementations.
"""

from abc import ABC
from abc import abstractmethod

from src.domain.order_request import OrderRequest
from src.domain.order import Order


class BrokerInterface(ABC):

    @abstractmethod
    def login(self) -> bool:
        """Authenticate with broker."""
        pass

    @abstractmethod
    def logout(self) -> None:
        """Logout broker session."""
        pass

    @abstractmethod
    def place_order(
        self,
        order_request: OrderRequest,
    ) -> Order:
        """Place order."""
        pass

    @abstractmethod
    def modify_order(
        self,
        order_id: str,
        price: float,
    ) -> bool:
        """Modify existing order."""
        pass

    @abstractmethod
    def cancel_order(
        self,
        order_id: str,
    ) -> bool:
        """Cancel order."""
        pass

    @abstractmethod
    def get_order(
        self,
        order_id: str,
    ) -> Order:
        """Fetch order details."""
        pass

    @abstractmethod
    def get_positions(self):
        """Return all open positions."""
        pass

    @abstractmethod
    def get_funds(self):
        """Return available funds."""
        pass

    @abstractmethod
    def connect_market_data(self):
        """Connect market data websocket."""
        pass

    @abstractmethod
    def disconnect_market_data(self):
        """Disconnect websocket."""
        pass