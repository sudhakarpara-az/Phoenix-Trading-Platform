"""
Phoenix Trading Platform

Custom Exceptions
"""


class PhoenixError(Exception):
    """
    Base exception for the Phoenix Trading Platform.
    """

    pass


class ConfigurationError(PhoenixError):
    """Raised when configuration is invalid."""

    pass


class ValidationError(PhoenixError):
    """Raised when startup validation fails."""

    pass


class BrokerConnectionError(PhoenixError):
    """Raised when broker connection fails."""

    pass


class StrategyError(PhoenixError):
    """Raised when strategy execution fails."""

    pass


class OrderExecutionError(PhoenixError):
    """Raised when order execution fails."""

    pass


__all__ = [
    "PhoenixError",
    "ConfigurationError",
    "ValidationError",
    "BrokerConnectionError",
    "StrategyError",
    "OrderExecutionError",
]