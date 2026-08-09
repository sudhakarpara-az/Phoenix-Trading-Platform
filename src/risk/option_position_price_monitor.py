"""
Phoenix M07 option position price monitor.

Maintains the latest valid option premium for contracts belonging
to currently managed positions.

Responsibilities:
    - Accept option-price ticks only for managed/open positions.
    - Reject invalid prices.
    - Reject stale or out-of-order ticks.
    - Maintain latest price by security ID.
    - Resolve latest price by FilledPositionId.
    - Expose immutable price snapshots.

No broker subscription logic, P&L calculation, target evaluation,
or stop-loss evaluation belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite
from threading import RLock

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.risk.position_registry import (
    PositionRegistry,
)


@dataclass(frozen=True, slots=True)
class OptionPriceTick:
    """
    One normalized option premium tick.

    security_id:
        Broker/security-master instrument identity.

    ltp:
        Current option premium.

    received_at:
        Timestamp when Phoenix received/normalized the tick.
    """

    security_id: str
    ltp: float
    received_at: datetime

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError(
                "security_id cannot be empty"
            )

        if not isfinite(
            self.ltp
        ):
            raise ValueError(
                "ltp must be finite"
            )

        if self.ltp <= 0:
            raise ValueError(
                "ltp must be greater than zero"
            )


@dataclass(frozen=True, slots=True)
class LatestPositionPrice:
    """
    Latest accepted price for one managed option contract.
    """

    security_id: str
    ltp: float
    received_at: datetime


class PriceUpdateStatus(str, Enum):
    """
    Result of attempting to process one tick.
    """

    ACCEPTED = "ACCEPTED"

    UNTRACKED_SECURITY = "UNTRACKED_SECURITY"

    NO_OPEN_POSITION = "NO_OPEN_POSITION"

    STALE_TICK = "STALE_TICK"


@dataclass(frozen=True, slots=True)
class PriceUpdateResult:
    status: PriceUpdateStatus

    tick: OptionPriceTick

    latest_price: LatestPositionPrice | None

    @property
    def accepted(self) -> bool:
        return (
            self.status
            is PriceUpdateStatus.ACCEPTED
        )


class OptionPositionPriceMonitor:
    """
    Maintains latest option prices for currently managed positions.

    PositionRegistry remains authoritative for which positions
    actually exist and whether they retain open quantity.
    """

    def __init__(
        self,
        *,
        registry: PositionRegistry,
    ) -> None:
        self._registry = registry

        self._latest_by_security: dict[
            str,
            LatestPositionPrice,
        ] = {}

        self._lock = RLock()

    def process_tick(
        self,
        tick: OptionPriceTick,
    ) -> PriceUpdateResult:
        """
        Process one normalized option tick.

        A tick is accepted only when:
            - the security belongs to a managed position
            - at least one matching position has open quantity
            - the tick timestamp is newer than the last accepted tick
        """

        matching_positions = tuple(
            position
            for position in self._registry.all()
            if (
                position.security_id
                == tick.security_id
            )
        )

        if not matching_positions:
            return PriceUpdateResult(
                status=(
                    PriceUpdateStatus
                    .UNTRACKED_SECURITY
                ),
                tick=tick,
                latest_price=None,
            )

        has_open_position = any(
            position.open_quantity > 0
            for position
            in matching_positions
        )

        if not has_open_position:
            return PriceUpdateResult(
                status=(
                    PriceUpdateStatus
                    .NO_OPEN_POSITION
                ),
                tick=tick,
                latest_price=None,
            )

        with self._lock:
            existing = (
                self._latest_by_security.get(
                    tick.security_id
                )
            )

            if (
                existing is not None
                and tick.received_at
                <= existing.received_at
            ):
                return PriceUpdateResult(
                    status=(
                        PriceUpdateStatus
                        .STALE_TICK
                    ),
                    tick=tick,
                    latest_price=existing,
                )

            latest = LatestPositionPrice(
                security_id=tick.security_id,
                ltp=tick.ltp,
                received_at=tick.received_at,
            )

            self._latest_by_security[
                tick.security_id
            ] = latest

            return PriceUpdateResult(
                status=(
                    PriceUpdateStatus
                    .ACCEPTED
                ),
                tick=tick,
                latest_price=latest,
            )

    def get_by_security_id(
        self,
        security_id: str,
    ) -> LatestPositionPrice | None:
        if not security_id.strip():
            raise ValueError(
                "security_id cannot be empty"
            )

        with self._lock:
            return (
                self._latest_by_security.get(
                    security_id
                )
            )

    def get_for_position(
        self,
        position_id: FilledPositionId,
    ) -> LatestPositionPrice | None:
        """
        Resolve latest price using M06 FilledPositionId.
        """

        position = self._registry.get(
            position_id
        )

        if position is None:
            return None

        return self.get_by_security_id(
            position.security_id
        )

    def require_for_position(
        self,
        position_id: FilledPositionId,
    ) -> LatestPositionPrice:
        latest = self.get_for_position(
            position_id
        )

        if latest is None:
            raise LookupError(
                "latest option price not available "
                f"for position {position_id.value}"
            )

        return latest

    def is_fresh(
        self,
        *,
        position_id: FilledPositionId,
        now: datetime,
        max_age: timedelta,
    ) -> bool:
        """
        True only when a price exists and its age does not
        exceed max_age.

        Future-dated prices are treated as invalid/stale.
        """

        if max_age.total_seconds() < 0:
            raise ValueError(
                "max_age cannot be negative"
            )

        latest = self.get_for_position(
            position_id
        )

        if latest is None:
            return False

        age = (
            now
            - latest.received_at
        )

        if age.total_seconds() < 0:
            return False

        return age <= max_age

    def tracked_security_ids(
        self,
    ) -> tuple[str, ...]:
        """
        Return security IDs currently represented by open
        managed positions.

        This is useful later for subscription coordination.
        """

        security_ids = {
            position.security_id
            for position
            in self._registry.open_positions()
        }

        return tuple(
            sorted(
                security_ids
            )
        )

    def latest_prices(
        self,
    ) -> tuple[
        LatestPositionPrice,
        ...
    ]:
        with self._lock:
            return tuple(
                self._latest_by_security.values()
            )

    def remove_security(
        self,
        security_id: str,
    ) -> bool:
        """
        Remove cached price state.

        Intended for controlled lifecycle cleanup after the
        final position using a security is closed.
        """

        if not security_id.strip():
            raise ValueError(
                "security_id cannot be empty"
            )

        with self._lock:
            return (
                self._latest_by_security.pop(
                    security_id,
                    None,
                )
                is not None
            )

    def clear(
        self,
    ) -> None:
        with self._lock:
            self._latest_by_security.clear()