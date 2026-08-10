"""
Phoenix M07 daily risk manager.

Aggregates day-level trading risk and controls whether NEW
entries remain eligible.

Responsibilities:
    - aggregate realized P&L
    - aggregate unrealized P&L
    - calculate total day P&L
    - count open / closed managed positions
    - enforce configurable daily-loss lock
    - enforce configurable daily-profit lock
    - enforce configurable closed-trade/position count
    - support explicit manual trading lock

Important:
    Daily locks apply to NEW ENTRY eligibility only.

    Existing position exits must never be blocked by this
    component.

No broker calls or order placement belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite
from threading import RLock

from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionPnL,
)


@dataclass(frozen=True, slots=True)
class DailyRiskConfig:
    """
    Optional Phoenix daily risk controls.

    None disables that particular limit.

    max_daily_loss_amount:
        Positive absolute loss threshold.

        Example:
            max_daily_loss_amount = 5000

        Lock occurs when:
            total_pnl <= -5000

    daily_profit_lock_amount:
        Positive profit threshold.

        Lock occurs when:
            total_pnl >= threshold

    max_closed_positions:
        Maximum completed managed positions allowed before
        new-entry trading is locked.
    """

    max_daily_loss_amount: float | None = None

    daily_profit_lock_amount: float | None = None

    max_closed_positions: int | None = None

    def __post_init__(self) -> None:
        monetary_limits = {
            "max_daily_loss_amount": (
                self.max_daily_loss_amount
            ),
            "daily_profit_lock_amount": (
                self.daily_profit_lock_amount
            ),
        }

        for name, value in monetary_limits.items():
            if value is None:
                continue

            if not isfinite(value):
                raise ValueError(
                    f"{name} must be finite"
                )

            if value <= 0:
                raise ValueError(
                    f"{name} must be greater than zero"
                )

        if (
            self.max_closed_positions is not None
            and self.max_closed_positions <= 0
        ):
            raise ValueError(
                "max_closed_positions must be greater than zero"
            )


class DailyRiskLockReason(str, Enum):
    NONE = "NONE"

    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"

    DAILY_PROFIT_LOCK = "DAILY_PROFIT_LOCK"

    MAX_CLOSED_POSITIONS = "MAX_CLOSED_POSITIONS"

    MANUAL_LOCK = "MANUAL_LOCK"


@dataclass(frozen=True, slots=True)
class DailyRiskSnapshot:
    """
    Point-in-time day-level risk view.
    """

    trading_date: date

    realized_pnl: float

    unrealized_pnl: float

    total_pnl: float

    open_positions: int

    closed_positions: int

    open_quantity: int

    new_entries_allowed: bool

    lock_reason: DailyRiskLockReason

    captured_at: datetime

    message: str | None = None

    def __post_init__(self) -> None:
        for name, value in {
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.total_pnl,
        }.items():
            if not isfinite(value):
                raise ValueError(
                    f"{name} must be finite"
                )

        expected_total = (
            self.realized_pnl
            + self.unrealized_pnl
        )

        if abs(
            self.total_pnl
            - expected_total
        ) > 1e-9:
            raise ValueError(
                "total_pnl must equal realized_pnl "
                "+ unrealized_pnl"
            )

        if self.open_positions < 0:
            raise ValueError(
                "open_positions cannot be negative"
            )

        if self.closed_positions < 0:
            raise ValueError(
                "closed_positions cannot be negative"
            )

        if self.open_quantity < 0:
            raise ValueError(
                "open_quantity cannot be negative"
            )

        if (
            self.new_entries_allowed
            and self.lock_reason
            is not DailyRiskLockReason.NONE
        ):
            raise ValueError(
                "allowed daily risk snapshot cannot "
                "contain lock reason"
            )

        if (
            not self.new_entries_allowed
            and self.lock_reason
            is DailyRiskLockReason.NONE
        ):
            raise ValueError(
                "locked daily risk snapshot requires "
                "lock reason"
            )


class DailyRiskManager:
    """
    Day-level entry risk gate.

    This class deliberately has no method such as
    `can_exit_position()`.

    Exit management remains allowed regardless of daily lock.
    """

    def __init__(
        self,
        *,
        registry: PositionRegistry,
        config: DailyRiskConfig | None = None,
    ) -> None:
        self._registry = registry

        self._config = (
            config
            or DailyRiskConfig()
        )

        self._manual_lock = False
        self._manual_lock_message: str | None = None

        self._lock = RLock()

    @property
    def registry(
        self,
    ) -> PositionRegistry:
        """
        Return the exact M07 registry used for daily-risk state.
        """

        return self._registry

    @property
    def config(
        self,
    ) -> DailyRiskConfig:
        return self._config

    def set_manual_lock(
        self,
        *,
        message: str | None = None,
    ) -> None:
        """
        Immediately prevent new entries.

        This does not affect exit processing.
        """

        if (
            message is not None
            and not message.strip()
        ):
            raise ValueError(
                "manual lock message cannot be empty"
            )

        with self._lock:
            self._manual_lock = True
            self._manual_lock_message = message

    def clear_manual_lock(
        self,
    ) -> None:
        with self._lock:
            self._manual_lock = False
            self._manual_lock_message = None

    def is_manually_locked(
        self,
    ) -> bool:
        with self._lock:
            return self._manual_lock

    def build_snapshot(
        self,
        *,
        trading_date: date,
        position_pnls: dict[
            str,
            PositionPnL,
        ],
        captured_at: datetime,
    ) -> DailyRiskSnapshot:
        """
        Build day-level risk snapshot.

        position_pnls is keyed by FilledPositionId.value.

        Every currently open managed position must have one
        current PositionPnL value.

        Closed positions may omit an external P&L snapshot
        because their realized P&L is already authoritative
        in ManagedPosition.realized_pnl.
        """

        positions = self._registry.all()

        realized_pnl = sum(
            position.realized_pnl
            for position in positions
        )

        unrealized_pnl = 0.0

        open_positions = 0
        closed_positions = 0
        open_quantity = 0

        for position in positions:
            if position.open_quantity > 0:
                open_positions += 1
                open_quantity += (
                    position.open_quantity
                )

                pnl = position_pnls.get(
                    position.position_id.value
                )

                if pnl is None:
                    raise ValueError(
                        "P&L snapshot required for open "
                        "managed position: "
                        f"{position.position_id.value}"
                    )

                unrealized_pnl += (
                    pnl.unrealized_pnl
                )

            if (
                position.state
                is ManagedPositionState.CLOSED
            ):
                closed_positions += 1

        total_pnl = (
            realized_pnl
            + unrealized_pnl
        )

        (
            allowed,
            reason,
            message,
        ) = self._evaluate_lock(
            total_pnl=total_pnl,
            closed_positions=closed_positions,
        )

        return DailyRiskSnapshot(
            trading_date=trading_date,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=total_pnl,
            open_positions=open_positions,
            closed_positions=closed_positions,
            open_quantity=open_quantity,
            new_entries_allowed=allowed,
            lock_reason=reason,
            captured_at=captured_at,
            message=message,
        )

    def _evaluate_lock(
        self,
        *,
        total_pnl: float,
        closed_positions: int,
    ) -> tuple[
        bool,
        DailyRiskLockReason,
        str | None,
    ]:
        """
        Lock priority:

            1. manual lock
            2. maximum daily loss
            3. daily profit lock
            4. maximum closed positions
            5. allowed
        """

        with self._lock:
            if self._manual_lock:
                return (
                    False,
                    DailyRiskLockReason.MANUAL_LOCK,
                    self._manual_lock_message
                    or "new entries manually disabled",
                )

        if (
            self._config.max_daily_loss_amount
            is not None
            and total_pnl
            <= -self._config.max_daily_loss_amount
        ):
            return (
                False,
                DailyRiskLockReason.MAX_DAILY_LOSS,
                "maximum daily loss threshold reached",
            )

        if (
            self._config.daily_profit_lock_amount
            is not None
            and total_pnl
            >= self._config.daily_profit_lock_amount
        ):
            return (
                False,
                DailyRiskLockReason.DAILY_PROFIT_LOCK,
                "daily profit lock threshold reached",
            )

        if (
            self._config.max_closed_positions
            is not None
            and closed_positions
            >= self._config.max_closed_positions
        ):
            return (
                False,
                DailyRiskLockReason
                .MAX_CLOSED_POSITIONS,
                "maximum closed position count reached",
            )

        return (
            True,
            DailyRiskLockReason.NONE,
            None,
        )