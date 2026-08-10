"""
Phoenix M07 position registry.

Stores and manages immutable ManagedPosition snapshots.

Responsibilities:
    - Register one FilledPosition exactly once.
    - Retrieve positions by position ID or risk ID.
    - Replace immutable ManagedPosition snapshots safely.
    - Query OPEN / PARTIALLY_EXITED / EXIT_PENDING / CLOSED positions.
    - Prevent accidental duplicate registration.

No broker calls, P&L calculation, stop calculation, or exit execution
belongs in this module.
"""

from __future__ import annotations

from threading import RLock

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


class DuplicatePositionError(RuntimeError):
    """
    Raised when the same M06 FilledPosition is registered twice.
    """


class DuplicateRiskIdError(RuntimeError):
    """
    Raised when a PositionRiskId is already assigned.
    """


class PositionNotFoundError(KeyError):
    """
    Raised when a managed position cannot be found.
    """


class PositionRegistry:
    """
    Thread-safe in-memory registry of M07 ManagedPosition snapshots.

    Position identity is anchored on M06 FilledPositionId.

    PositionRiskId is a secondary M07 lookup identity.
    """

    def __init__(self) -> None:
        self._by_position_id: dict[
            str,
            ManagedPosition,
        ] = {}

        self._risk_to_position: dict[
            str,
            str,
        ] = {}

        self._lock = RLock()

    def register(
        self,
        position: ManagedPosition,
    ) -> ManagedPosition:
        """
        Register a new managed position.

        A FilledPositionId may only be registered once.
        A PositionRiskId may only belong to one position.
        """

        position_key = (
            position.position_id.value
        )

        risk_key = (
            position.risk_id.value
        )

        with self._lock:
            if (
                position_key
                in self._by_position_id
            ):
                raise DuplicatePositionError(
                    "managed position already registered: "
                    f"{position_key}"
                )

            if (
                risk_key
                in self._risk_to_position
            ):
                raise DuplicateRiskIdError(
                    "position risk id already registered: "
                    f"{risk_key}"
                )

            self._by_position_id[
                position_key
            ] = position

            self._risk_to_position[
                risk_key
            ] = position_key

            return position

    def replace(
        self,
        position: ManagedPosition,
    ) -> ManagedPosition:
        """
        Replace the current immutable snapshot for an existing position.

        Identity cannot change during replacement:
            - FilledPositionId remains the same.
            - PositionRiskId remains the same.
        """

        position_key = (
            position.position_id.value
        )

        with self._lock:
            existing = (
                self._by_position_id.get(
                    position_key
                )
            )

            if existing is None:
                raise PositionNotFoundError(
                    "managed position not found: "
                    f"{position_key}"
                )

            if (
                existing.risk_id
                != position.risk_id
            ):
                raise ValueError(
                    "position risk id cannot change "
                    "during replacement"
                )

            if (
                existing.position.position_id
                != position.position.position_id
            ):
                raise ValueError(
                    "filled position identity cannot change "
                    "during replacement"
                )

            if (
                position.updated_at
                < existing.updated_at
            ):
                raise ValueError(
                    "replacement snapshot cannot be older "
                    "than current snapshot"
                )

            self._by_position_id[
                position_key
            ] = position

            return position

    def get(
        self,
        position_id: FilledPositionId,
    ) -> ManagedPosition | None:
        """
        Retrieve position by M06 FilledPositionId.
        """

        with self._lock:
            return self._by_position_id.get(
                position_id.value
            )

    def require(
        self,
        position_id: FilledPositionId,
    ) -> ManagedPosition:
        """
        Retrieve position or raise PositionNotFoundError.
        """

        position = self.get(
            position_id
        )

        if position is None:
            raise PositionNotFoundError(
                "managed position not found: "
                f"{position_id.value}"
            )

        return position

    def get_by_risk_id(
        self,
        risk_id: PositionRiskId,
    ) -> ManagedPosition | None:
        """
        Retrieve position using M07 PositionRiskId.
        """

        with self._lock:
            position_key = (
                self._risk_to_position.get(
                    risk_id.value
                )
            )

            if position_key is None:
                return None

            return self._by_position_id.get(
                position_key
            )

    def contains(
        self,
        position_id: FilledPositionId,
    ) -> bool:
        with self._lock:
            return (
                position_id.value
                in self._by_position_id
            )

    def count(
        self,
    ) -> int:
        with self._lock:
            return len(
                self._by_position_id
            )

    def all(
        self,
    ) -> tuple[
        ManagedPosition,
        ...
    ]:
        """
        Return immutable snapshot collection.
        """

        with self._lock:
            return tuple(
                self._by_position_id.values()
            )

    def by_state(
        self,
        state: ManagedPositionState,
    ) -> tuple[
        ManagedPosition,
        ...
    ]:
        """
        Return all positions in one exact management state.
        """

        with self._lock:
            return tuple(
                position
                for position
                in self._by_position_id.values()
                if position.state is state
            )

    def open_positions(
        self,
    ) -> tuple[
        ManagedPosition,
        ...
    ]:
        """
        Positions that still contain open quantity.

        Includes:
            OPEN
            PARTIALLY_EXITED
            EXIT_PENDING
            RECONCILIATION_REQUIRED

        CLOSED positions are excluded.
        """

        with self._lock:
            return tuple(
                position
                for position
                in self._by_position_id.values()
                if position.open_quantity > 0
            )

    def closed_positions(
        self,
    ) -> tuple[
        ManagedPosition,
        ...
    ]:
        with self._lock:
            return tuple(
                position
                for position
                in self._by_position_id.values()
                if (
                    position.state
                    is ManagedPositionState.CLOSED
                )
            )

    def has_open_position_for_level(
        self,
    *,
    level: EntryLevel,
    ) -> bool:
        """
        True when any managed position at the supplied KS entry
        level still has open quantity.

        This will later support M04/M07 re-entry synchronization.
        """

        with self._lock:
            return any(
                position.position.level
                is level
                and position.open_quantity > 0
                for position
                in self._by_position_id.values()
            )

    def clear(
        self,
    ) -> None:
        """
        Controlled test/session reset helper.
        """

        with self._lock:
            self._by_position_id.clear()
            self._risk_to_position.clear()
