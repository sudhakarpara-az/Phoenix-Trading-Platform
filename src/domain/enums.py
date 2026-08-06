"""
Phoenix Trading Platform

Domain Enums
"""

from enum import Enum


class OptionSide(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class KSLevel(str, Enum):
    K5 = "K5"
    K6 = "K6"
    K7 = "K7"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TradeStatus(str, Enum):
    WAITING = "WAITING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"