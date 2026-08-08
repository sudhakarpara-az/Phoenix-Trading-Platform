"""
Phoenix M08 runtime health domain models.

Defines runtime-component health observations and aggregate
runtime health status.

No database, broker, or market-feed implementation belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class RuntimeHealthStatus(
    str,
    Enum,
):
    HEALTHY = "HEALTHY"

    DEGRADED = "DEGRADED"

    FAILED = "FAILED"


class RuntimeHealthComponent(
    str,
    Enum,
):
    DATABASE = "DATABASE"

    MARKET_DATA = "MARKET_DATA"

    RECOVERY = "RECOVERY"

    EXECUTION = "EXECUTION"

    RISK = "RISK"

    INTERNAL = "INTERNAL"


@dataclass(
    frozen=True,
    slots=True,
)
class ComponentHealthResult:
    component: RuntimeHealthComponent

    status: RuntimeHealthStatus

    checked_at: datetime

    message: str | None = None

    critical: bool = True

    def __post_init__(
        self,
    ) -> None:
        if self.message is not None:
            message = self.message.strip()

            if not message:
                raise ValueError(
                    "health result message cannot be empty"
                )

            if message != self.message:
                object.__setattr__(
                    self,
                    "message",
                    message,
                )

    @property
    def healthy(
        self,
    ) -> bool:
        return (
            self.status
            is RuntimeHealthStatus.HEALTHY
        )


@dataclass(
    frozen=True,
    slots=True,
)
class RuntimeHealthSnapshot:
    status: RuntimeHealthStatus

    checked_at: datetime

    components: tuple[
        ComponentHealthResult,
        ...
    ]

    @property
    def failed_components(
        self,
    ) -> tuple[
        ComponentHealthResult,
        ...
    ]:
        return tuple(
            item
            for item in self.components
            if (
                item.status
                is RuntimeHealthStatus.FAILED
            )
        )

    @property
    def degraded_components(
        self,
    ) -> tuple[
        ComponentHealthResult,
        ...
    ]:
        return tuple(
            item
            for item in self.components
            if (
                item.status
                is RuntimeHealthStatus.DEGRADED
            )
        )

    @property
    def healthy(
        self,
    ) -> bool:
        return (
            self.status
            is RuntimeHealthStatus.HEALTHY
        )


class RuntimeHealthCheck(
    Protocol,
):
    """
    Narrow check contract consumed by RuntimeHealthSupervisor.
    """

    @property
    def component(
        self,
    ) -> RuntimeHealthComponent:
        ...

    @property
    def critical(
        self,
    ) -> bool:
        ...

    def check(
        self,
        *,
        checked_at: datetime,
    ) -> ComponentHealthResult:
        ...