"""
Phoenix M07 persistent position P&L tracker.

Maintains authoritative in-memory P&L state for managed positions.

Responsibilities:
    - register managed positions for P&L tracking
    - record actual executed SELL fills
    - maintain latest option mark / LTP
    - calculate realized P&L incrementally
    - calculate unrealized P&L on remaining quantity
    - expose latest position P&L snapshots
    - prevent over-exit accounting
    - reject stale market marks

Actual execution prices remain authoritative.

No broker calls or order submission belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from threading import RLock

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.risk.position_pnl_calculator import (
    ExitFill,
)
from src.risk.risk_types import (
    ManagedPosition,
    PositionPnL,
)


@dataclass(frozen=True, slots=True)
class PositionPnLState:
    """
    Current authoritative P&L state for one managed position.
    """

    position_id: FilledPositionId

    entry_price: float

    original_quantity: int

    open_quantity: int

    closed_quantity: int

    realized_pnl: float

    unrealized_pnl: float

    total_pnl: float

    unrealized_points: float

    latest_ltp: float | None

    latest_mark_at: datetime | None

    exit_fills: tuple[
        ExitFill,
        ...
    ]

    updated_at: datetime

    @property
    def is_closed(
        self,
    ) -> bool:
        return self.open_quantity == 0


class PositionPnLTracker:
    """
    Thread-safe P&L ledger for M07 positions.
    """

    def __init__(
        self,
    ) -> None:
        self._states: dict[
            str,
            PositionPnLState,
        ] = {}

        self._lock = RLock()

    def register(
        self,
        *,
        position: ManagedPosition,
        registered_at: datetime,
    ) -> PositionPnLState:
        """
        Register one managed position.

        Initial realized P&L comes from ManagedPosition so a
        partially exited position can be reconstructed safely.

        Initial unrealized P&L remains zero until a mark arrives.
        """

        key = (
            position.position_id.value
        )

        with self._lock:
            if key in self._states:
                raise ValueError(
                    "position already registered for "
                    "P&L tracking"
                )

            if (
                registered_at
                < position.created_at
            ):
                raise ValueError(
                    "registered_at cannot be before "
                    "managed position creation"
                )

            state = PositionPnLState(
                position_id=position.position_id,
                entry_price=position.entry_price,
                original_quantity=(
                    position.original_quantity
                ),
                open_quantity=(
                    position.open_quantity
                ),
                closed_quantity=(
                    position.closed_quantity
                ),
                realized_pnl=(
                    position.realized_pnl
                ),
                unrealized_pnl=0.0,
                total_pnl=(
                    position.realized_pnl
                ),
                unrealized_points=0.0,
                latest_ltp=None,
                latest_mark_at=None,
                exit_fills=(),
                updated_at=registered_at,
            )

            self._states[
                key
            ] = state

            return state

    def record_exit_fill(
        self,
        *,
        position_id: FilledPositionId,
        quantity: int,
        price: float,
        filled_at: datetime,
    ) -> PositionPnLState:
        """
        Record one actual executed SELL fill.

        Realized P&L:
            (exit fill - actual entry fill) * quantity
        """

        if quantity <= 0:
            raise ValueError(
                "exit fill quantity must be "
                "greater than zero"
            )

        if not isfinite(
            price
        ):
            raise ValueError(
                "exit fill price must be finite"
            )

        if price <= 0:
            raise ValueError(
                "exit fill price must be "
                "greater than zero"
            )

        with self._lock:
            state = self._require_unlocked(
                position_id
            )

            if quantity > state.open_quantity:
                raise ValueError(
                    "exit fill quantity cannot exceed "
                    "tracked open quantity"
                )

            if filled_at < state.updated_at:
                raise ValueError(
                    "exit fill timestamp cannot be "
                    "before current P&L state"
                )

            fill = ExitFill(
                quantity=quantity,
                price=price,
                filled_at=filled_at,
            )

            realized_for_fill = (
                price
                - state.entry_price
            ) * quantity

            new_open_quantity = (
                state.open_quantity
                - quantity
            )

            new_closed_quantity = (
                state.closed_quantity
                + quantity
            )

            new_realized_pnl = (
                state.realized_pnl
                + realized_for_fill
            )

            if state.latest_ltp is None:
                unrealized_points = 0.0
                unrealized_pnl = 0.0

            else:
                unrealized_points = (
                    state.latest_ltp
                    - state.entry_price
                )

                unrealized_pnl = (
                    unrealized_points
                    * new_open_quantity
                )

            total_pnl = (
                new_realized_pnl
                + unrealized_pnl
            )

            updated = PositionPnLState(
                position_id=state.position_id,
                entry_price=state.entry_price,
                original_quantity=(
                    state.original_quantity
                ),
                open_quantity=(
                    new_open_quantity
                ),
                closed_quantity=(
                    new_closed_quantity
                ),
                realized_pnl=(
                    new_realized_pnl
                ),
                unrealized_pnl=(
                    unrealized_pnl
                ),
                total_pnl=total_pnl,
                unrealized_points=(
                    unrealized_points
                ),
                latest_ltp=state.latest_ltp,
                latest_mark_at=(
                    state.latest_mark_at
                ),
                exit_fills=(
                    state.exit_fills
                    + (fill,)
                ),
                updated_at=filled_at,
            )

            self._states[
                position_id.value
            ] = updated

            return updated

    def mark_to_market(
        self,
        *,
        position_id: FilledPositionId,
        ltp: float,
        marked_at: datetime,
    ) -> PositionPnLState:
        """
        Update unrealized P&L from current option LTP.

        Older/equal marks are rejected to protect P&L state from
        out-of-order market data.
        """

        if not isfinite(
            ltp
        ):
            raise ValueError(
                "ltp must be finite"
            )

        if ltp <= 0:
            raise ValueError(
                "ltp must be greater than zero"
            )

        with self._lock:
            state = self._require_unlocked(
                position_id
            )

            if (
                state.latest_mark_at is not None
                and marked_at
                <= state.latest_mark_at
            ):
                raise ValueError(
                    "mark timestamp must be newer than "
                    "latest mark"
                )

            unrealized_points = (
                ltp
                - state.entry_price
            )

            unrealized_pnl = (
                unrealized_points
                * state.open_quantity
            )

            total_pnl = (
                state.realized_pnl
                + unrealized_pnl
            )

            updated = PositionPnLState(
                position_id=state.position_id,
                entry_price=state.entry_price,
                original_quantity=(
                    state.original_quantity
                ),
                open_quantity=(
                    state.open_quantity
                ),
                closed_quantity=(
                    state.closed_quantity
                ),
                realized_pnl=(
                    state.realized_pnl
                ),
                unrealized_pnl=(
                    unrealized_pnl
                ),
                total_pnl=total_pnl,
                unrealized_points=(
                    unrealized_points
                ),
                latest_ltp=ltp,
                latest_mark_at=marked_at,
                exit_fills=state.exit_fills,
                updated_at=marked_at,
            )

            self._states[
                position_id.value
            ] = updated

            return updated

    def get(
        self,
        position_id: FilledPositionId,
    ) -> PositionPnLState | None:
        with self._lock:
            return self._states.get(
                position_id.value
            )

    def require(
        self,
        position_id: FilledPositionId,
    ) -> PositionPnLState:
        with self._lock:
            return self._require_unlocked(
                position_id
            )

    def to_position_pnl(
        self,
        position_id: FilledPositionId,
    ) -> PositionPnL:
        """
        Convert tracker state into the existing M07 PositionPnL
        domain model consumed by T05/T13.
        """

        state = self.require(
            position_id
        )

        return PositionPnL(
            realized_pnl=(
                state.realized_pnl
            ),
            unrealized_pnl=(
                state.unrealized_pnl
            ),
            total_pnl=(
                state.total_pnl
            ),
            unrealized_points=(
                state.unrealized_points
            ),
            calculated_at=state.updated_at,
        )

    def all_states(
        self,
    ) -> tuple[
        PositionPnLState,
        ...
    ]:
        with self._lock:
            return tuple(
                self._states.values()
            )

    def pnl_map(
        self,
    ) -> dict[
        str,
        PositionPnL,
    ]:
        """
        Produce the map expected by DailyRiskManager.
        """

        with self._lock:
            return {
                key: PositionPnL(
                    realized_pnl=(
                        state.realized_pnl
                    ),
                    unrealized_pnl=(
                        state.unrealized_pnl
                    ),
                    total_pnl=(
                        state.total_pnl
                    ),
                    unrealized_points=(
                        state.unrealized_points
                    ),
                    calculated_at=(
                        state.updated_at
                    ),
                )
                for key, state
                in self._states.items()
            }

    def clear(
        self,
    ) -> None:
        with self._lock:
            self._states.clear()

    def _require_unlocked(
        self,
        position_id: FilledPositionId,
    ) -> PositionPnLState:
        state = self._states.get(
            position_id.value
        )

        if state is None:
            raise KeyError(
                "position is not registered for "
                f"P&L tracking: {position_id.value}"
            )

        return state