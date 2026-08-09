"""
Phoenix M07 stop-loss trigger monitor.

Evaluates whether a managed long-option position has reached
or crossed its configured premium stop price.

Responsibilities:
    - Consume latest option premium from T06.
    - Require fresh market data.
    - Trigger when LTP <= configured stop price.
    - Handle gaps below the stop.
    - Prevent duplicate stop-loss events.
    - Ignore closed positions.
    - Respect disabled / already-triggered stop state.

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
    StopLossState,
)


class StopLossTriggerStatus(str, Enum):
    NOT_TRIGGERED = "NOT_TRIGGERED"

    TRIGGERED = "TRIGGERED"

    NO_STOP_LOSS = "NO_STOP_LOSS"

    STOP_LOSS_DISABLED = "STOP_LOSS_DISABLED"

    ALREADY_TRIGGERED = "ALREADY_TRIGGERED"

    POSITION_CLOSED = "POSITION_CLOSED"

    PRICE_NOT_AVAILABLE = "PRICE_NOT_AVAILABLE"

    STALE_PRICE = "STALE_PRICE"


@dataclass(frozen=True, slots=True)
class StopLossTriggerResult:
    status: StopLossTriggerStatus

    position_id: FilledPositionId

    trigger: RiskTriggerType

    current_ltp: float | None

    stop_price: float | None

    risk_points: float | None

    price_received_at: datetime | None

    evaluated_at: datetime

    @property
    def triggered(self) -> bool:
        return (
            self.status
            is StopLossTriggerStatus.TRIGGERED
        )


class StopLossTriggerMonitor:
    """
    Evaluates stop-loss conditions for M07 managed positions.

    One stop-loss event is emitted per position until explicitly
    reset by upstream lifecycle/reconciliation logic.
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
    ) -> StopLossTriggerResult:
        """
        Evaluate stop-loss condition for one position.
        """

        position_key = (
            position.position_id.value
        )

        # --------------------------------------------------
        # Closed positions cannot generate another exit.
        # --------------------------------------------------

        if (
            position.state
            is ManagedPositionState.CLOSED
            or position.open_quantity <= 0
        ):
            return self._result(
                status=(
                    StopLossTriggerStatus
                    .POSITION_CLOSED
                ),
                position=position,
                price=None,
                evaluated_at=evaluated_at,
            )

        stop = position.stop_loss

        # --------------------------------------------------
        # No stop configured.
        # --------------------------------------------------

        if stop is None:
            return self._result(
                status=(
                    StopLossTriggerStatus
                    .NO_STOP_LOSS
                ),
                position=position,
                price=None,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Domain stop state already prevents re-trigger.
        # --------------------------------------------------

        if (
            stop.state
            is StopLossState.TRIGGERED
        ):
            return self._result(
                status=(
                    StopLossTriggerStatus
                    .ALREADY_TRIGGERED
                ),
                position=position,
                price=None,
                evaluated_at=evaluated_at,
            )

        if (
            stop.state
            in {
                StopLossState.DISABLED,
                StopLossState.NOT_CONFIGURED,
            }
        ):
            return self._result(
                status=(
                    StopLossTriggerStatus
                    .STOP_LOSS_DISABLED
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
                        StopLossTriggerStatus
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
                    StopLossTriggerStatus
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
            position_id=position.position_id,
            now=evaluated_at,
            max_age=self._max_price_age,
        ):
            return self._result(
                status=(
                    StopLossTriggerStatus
                    .STALE_PRICE
                ),
                position=position,
                price=latest,
                evaluated_at=evaluated_at,
            )

        # --------------------------------------------------
        # Long-option stop evaluation:
        #
        #     LTP <= stop price
        #
        # means configured downside threshold has been reached.
        # --------------------------------------------------

        if (
            latest.ltp
            > stop.stop_price
        ):
            return self._result(
                status=(
                    StopLossTriggerStatus
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
                        StopLossTriggerStatus
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
            status=(
                StopLossTriggerStatus.TRIGGERED
            ),
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
        Controlled lifecycle reset only.

        Do not use this as an automatic retry mechanism.
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
        with self._lock:
            self._triggered_positions.clear()

    @staticmethod
    def _result(
        *,
        status: StopLossTriggerStatus,
        position: ManagedPosition,
        price: LatestPositionPrice | None,
        evaluated_at: datetime,
    ) -> StopLossTriggerResult:
        stop = position.stop_loss

        return StopLossTriggerResult(
            status=status,
            position_id=position.position_id,
            trigger=(
                RiskTriggerType.STOP_LOSS
                if status
                is StopLossTriggerStatus.TRIGGERED
                else RiskTriggerType.NONE
            ),
            current_ltp=(
                price.ltp
                if price is not None
                else None
            ),
            stop_price=(
                stop.stop_price
                if stop is not None
                else None
            ),
            risk_points=(
                stop.risk_points
                if stop is not None
                else None
            ),
            price_received_at=(
                price.received_at
                if price is not None
                else None
            ),
            evaluated_at=evaluated_at,
        )