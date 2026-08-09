"""
Phoenix M07 target trigger monitor.

Evaluates whether a managed long-option position has reached
its configured executable target premium.

Responsibilities:
    - Consume latest option premium from T06.
    - Require fresh market data.
    - Detect entry into / beyond the target booking zone.
    - Prevent duplicate target-trigger events.
    - Ignore positions that are already closed.
    - Respect disabled / already-triggered target state.

No broker order placement belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
)
from enum import Enum
from threading import RLock

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.risk.option_position_price_monitor import (
    LatestPositionPrice,
    OptionPositionPriceMonitor,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    RiskTriggerType,
    TargetState,
)


class TargetTriggerStatus(str, Enum):
    """
    Outcome of one target evaluation.
    """

    NOT_TRIGGERED = "NOT_TRIGGERED"

    TRIGGERED = "TRIGGERED"

    NO_TARGET = "NO_TARGET"

    TARGET_DISABLED = "TARGET_DISABLED"

    ALREADY_TRIGGERED = "ALREADY_TRIGGERED"

    POSITION_CLOSED = "POSITION_CLOSED"

    PRICE_NOT_AVAILABLE = "PRICE_NOT_AVAILABLE"

    STALE_PRICE = "STALE_PRICE"


@dataclass(frozen=True, slots=True)
class TargetTriggerResult:
    """
    Result of evaluating one managed position target.
    """

    status: TargetTriggerStatus

    position_id: FilledPositionId

    trigger: RiskTriggerType

    current_ltp: float | None

    executable_target_price: float | None

    mapped_target_price: float | None

    booking_zone_start: float | None

    booking_zone_end: float | None

    price_received_at: datetime | None

    evaluated_at: datetime

    @property
    def triggered(self) -> bool:
        return (
            self.status
            is TargetTriggerStatus.TRIGGERED
        )


class TargetTriggerMonitor:
    """
    Evaluates target conditions for M07 managed positions.

    A position produces at most one target-trigger event until
    the monitor is explicitly reset for that position.

    Later M07 lifecycle logic will normally move the position to
    EXIT_PENDING immediately after TRIGGERED.
    """

    def __init__(
        self,
        *,
        price_monitor: OptionPositionPriceMonitor,
        max_price_age: timedelta = timedelta(
            seconds=5
        ),
    ) -> None:
        if max_price_age.total_seconds() < 0:
            raise ValueError(
                "max_price_age cannot be negative"
            )

        self._price_monitor = (
            price_monitor
        )

        self._max_price_age = (
            max_price_age
        )

        self._triggered_positions: set[
            str
        ] = set()

        self._lock = RLock()

    @property
    def max_price_age(
        self,
    ) -> timedelta:
        return self._max_price_age

    def evaluate(
        self,
        *,
        position: ManagedPosition,
        evaluated_at: datetime,
    ) -> TargetTriggerResult:
        """
        Evaluate target condition for one position.
        """

        position_key = (
            position.position_id.value
        )

        # --------------------------------------------------
        # Closed positions cannot generate exits.
        # --------------------------------------------------

        if (
            position.state
            is ManagedPositionState.CLOSED
            or position.open_quantity <= 0
        ):
            return self._result(
                status=(
                    TargetTriggerStatus
                    .POSITION_CLOSED
                ),
                position=position,
                price=None,
                evaluated_at=evaluated_at,
            )

        target = position.target

        # --------------------------------------------------
        # No target configured.
        # --------------------------------------------------

        if target is None:
            return self._result(
                status=TargetTriggerStatus.NO_TARGET,
                position=position,
                price=None,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Target already marked by lifecycle state.
        # --------------------------------------------------

        if (
            target.state
            is TargetState.TRIGGERED
        ):
            return self._result(
                status=(
                    TargetTriggerStatus
                    .ALREADY_TRIGGERED
                ),
                position=position,
                price=None,
                evaluated_at=evaluated_at,
            )

        if (
            target.state
            in {
                TargetState.DISABLED,
                TargetState.NOT_CONFIGURED,
            }
        ):
            return self._result(
                status=(
                    TargetTriggerStatus
                    .TARGET_DISABLED
                ),
                position=position,
                price=None,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Internal duplicate protection.
        # --------------------------------------------------

        with self._lock:
            if (
                position_key
                in self._triggered_positions
            ):
                return self._result(
                    status=(
                        TargetTriggerStatus
                        .ALREADY_TRIGGERED
                    ),
                    position=position,
                    price=(
                        self._price_monitor
                        .get_for_position(
                            position.position_id
                        )
                    ),
                    evaluated_at=evaluated_at,
                )

        # --------------------------------------------------
        # Price availability.
        # --------------------------------------------------

        latest = (
            self._price_monitor
            .get_for_position(
                position.position_id
            )
        )

        if latest is None:
            return self._result(
                status=(
                    TargetTriggerStatus
                    .PRICE_NOT_AVAILABLE
                ),
                position=position,
                price=None,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Freshness guard.
        # --------------------------------------------------

        if not self._price_monitor.is_fresh(
            position_id=(
                position.position_id
            ),
            now=evaluated_at,
            max_age=self._max_price_age,
        ):
            return self._result(
                status=(
                    TargetTriggerStatus
                    .STALE_PRICE
                ),
                position=position,
                price=latest,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Target evaluation.
        #
        # For long options:
        #
        #     LTP >= executable target
        #
        # means profit-booking trigger reached.
        # --------------------------------------------------

        if (
            latest.ltp
            < target.executable_price
        ):
            return self._result(
                status=(
                    TargetTriggerStatus
                    .NOT_TRIGGERED
                ),
                position=position,
                price=latest,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Atomic duplicate-event protection.
        # --------------------------------------------------

        with self._lock:
            if (
                position_key
                in self._triggered_positions
            ):
                return self._result(
                    status=(
                        TargetTriggerStatus
                        .ALREADY_TRIGGERED
                    ),
                    position=position,
                    price=latest,
                    evaluated_at=evaluated_at,
                )

            self._triggered_positions.add(
                position_key
            )

        return self._result(
            status=TargetTriggerStatus.TRIGGERED,
            position=position,
            price=latest,
            evaluated_at=evaluated_at,
        )

    def has_triggered(
        self,
        position_id: FilledPositionId,
    ) -> bool:
        with self._lock:
            return (
                position_id.value
                in self._triggered_positions
            )

    def reset_position(
        self,
        position_id: FilledPositionId,
    ) -> bool:
        """
        Controlled lifecycle reset.

        This should only be used when a previous target trigger
        has been explicitly invalidated/reconciled upstream.

        It must not be used as an automatic retry mechanism.
        """

        with self._lock:
            if (
                position_id.value
                not in self._triggered_positions
            ):
                return False

            self._triggered_positions.remove(
                position_id.value
            )

            return True

    def clear(
        self,
    ) -> None:
        """
        Controlled test/session reset.
        """

        with self._lock:
            self._triggered_positions.clear()

    @staticmethod
    def _result(
        *,
        status: TargetTriggerStatus,
        position: ManagedPosition,
        price: LatestPositionPrice | None,
        evaluated_at: datetime,
    ) -> TargetTriggerResult:
        target = position.target

        return TargetTriggerResult(
            status=status,
            position_id=position.position_id,
            trigger=(
                RiskTriggerType.TARGET
                if status
                is TargetTriggerStatus.TRIGGERED
                else RiskTriggerType.NONE
            ),
            current_ltp=(
                price.ltp
                if price is not None
                else None
            ),
            executable_target_price=(
                target.executable_price
                if target is not None
                else None
            ),
            mapped_target_price=(
                target.mapped_target_price
                if target is not None
                else None
            ),
            booking_zone_start=(
                target.booking_zone_start
                if target is not None
                else None
            ),
            booking_zone_end=(
                target.booking_zone_end
                if target is not None
                else None
            ),
            price_received_at=(
                price.received_at
                if price is not None
                else None
            ),
            evaluated_at=evaluated_at,
        )