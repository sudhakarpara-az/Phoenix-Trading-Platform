"""
Strategy State

Defines the lifecycle states of the Phoenix Strategy.
"""

from enum import Enum


class StrategyState(Enum):
    """
    Current lifecycle state of the strategy.
    """

    IDLE = "IDLE"
    WAITING_FOR_ENTRY = "WAITING_FOR_ENTRY"
    POSITION_OPEN = "POSITION_OPEN"
    POSITION_CLOSED = "POSITION_CLOSED"
    FORCE_EXIT = "FORCE_EXIT"
    DISABLED = "DISABLED"