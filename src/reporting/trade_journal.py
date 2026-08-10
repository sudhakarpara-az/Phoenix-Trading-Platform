"""
Phoenix M12 durable trade-journal projection.

The journal reads M06/M07/M10 persistence only.

No reporting method writes or repairs durable state.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from src.database.schema import (
    OrderFillRecord,
    OrderRecord,
    PnLSnapshotRecord,
    PositionRecord,
)
from src.reporting.reporting_types import (
    TradeJournalEntry,
)


class _OrderRepositoryReader(
    Protocol,
):
    """
    M12 read-only view of the existing order repository.
    """

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        ...


class _OrderFillRepositoryReader(
    Protocol,
):
    """
    M12 read-only view of the existing fill repository.
    """

    def list_by_order(
        self,
        order_intent_id: str,
    ) -> tuple[
        OrderFillRecord,
        ...,
    ]:
        ...


class _PositionRepositoryReader(
    Protocol,
):
    """
    M12 read-only view of the existing position repository.
    """

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        PositionRecord,
        ...,
    ]:
        ...


class _PnLSnapshotRepositoryReader(
    Protocol,
):
    """
    M12 read-only view of the existing P&L snapshot repository.
    """

    def list_by_position(
        self,
        position_id: str,
    ) -> tuple[
        PnLSnapshotRecord,
        ...,
    ]:
        ...


class TradeJournalIntegrityError(
    RuntimeError,
):
    """
    Durable records required for a trustworthy journal are
    structurally inconsistent.
    """


class TradeJournalService:
    """
    Builds immutable trade-journal entries from durable Phoenix
    repositories.

    PositionRecord remains authoritative for:
        - position identity,
        - entry price,
        - quantity already applied,
        - realized P&L,
        - lifecycle timestamps.

    OrderFillRecord remains authoritative for actual broker
    execution prices and quantities.
    """

    def __init__(
        self,
        *,
        order_repository: _OrderRepositoryReader,
        order_fill_repository: _OrderFillRepositoryReader,
        position_repository: _PositionRepositoryReader,
        pnl_repository: _PnLSnapshotRepositoryReader,
    ) -> None:
        self._order_repository = order_repository
        self._order_fill_repository = order_fill_repository
        self._position_repository = position_repository
        self._pnl_repository = pnl_repository

    def list_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        TradeJournalEntry,
        ...,
    ]:
        runtime_id = self._normalize_runtime_id(
            runtime_id
        )

        positions = tuple(
            self._position_repository.list_by_runtime(
                runtime_id
            )
        )

        orders = tuple(
            self._order_repository.list_by_runtime(
                runtime_id
            )
        )

        order_by_id = {
            order.order_intent_id: order
            for order in orders
        }

        exit_orders_by_position: dict[
            str,
            list[
                OrderRecord
            ],
        ] = defaultdict(
            list
        )

        for order in orders:
            if (
                order.side == "SELL"
                and order.position_id is not None
            ):
                exit_orders_by_position[
                    order.position_id
                ].append(
                    order
                )

        entries = [
            self._build_entry(
                runtime_id=runtime_id,
                position=position,
                order_by_id=order_by_id,
                exit_orders=tuple(
                    exit_orders_by_position.get(
                        position.position_id,
                        (),
                    )
                ),
            )
            for position in positions
        ]

        return tuple(
            sorted(
                entries,
                key=lambda item: (
                    item.opened_at,
                    item.position_id,
                ),
            )
        )

    def _build_entry(
        self,
        *,
        runtime_id: str,
        position: PositionRecord,
        order_by_id: dict[
            str,
            OrderRecord,
        ],
        exit_orders: tuple[
            OrderRecord,
            ...,
        ],
    ) -> TradeJournalEntry:
        if position.runtime_id != runtime_id:
            raise TradeJournalIntegrityError(
                "position runtime_id does not match "
                f"requested runtime: {position.position_id}"
            )

        entry_order = order_by_id.get(
            position.entry_order_intent_id
        )

        if entry_order is None:
            raise TradeJournalIntegrityError(
                "durable PositionRecord has no matching "
                "entry OrderRecord: "
                f"{position.position_id}"
            )

        if entry_order.side != "BUY":
            raise TradeJournalIntegrityError(
                "PositionRecord entry order must be BUY: "
                f"{position.position_id}"
            )

        (
            exit_fill_count,
            exit_filled_quantity,
            exit_notional,
        ) = self._exit_fill_totals(
            exit_orders
        )

        average_exit_price = None

        if exit_filled_quantity > 0:
            average_exit_price = (
                exit_notional
                / exit_filled_quantity
            )

        latest_pnl = self._latest_pnl(
            position.position_id
        )

        latest_unrealized_pnl = 0.0
        latest_total_pnl = position.realized_pnl
        latest_ltp = None
        latest_pnl_at = None

        if latest_pnl is not None:
            latest_unrealized_pnl = (
                latest_pnl.unrealized_pnl
            )

            latest_total_pnl = (
                latest_pnl.total_pnl
            )

            latest_ltp = latest_pnl.ltp
            latest_pnl_at = latest_pnl.captured_at

        return TradeJournalEntry(
            runtime_id=runtime_id,
            position_id=position.position_id,
            signal_id=position.signal_id,
            entry_order_intent_id=(
                position.entry_order_intent_id
            ),
            security_id=position.security_id,
            symbol=position.symbol,
            option_type=position.option_type,
            level=position.level,
            original_quantity=(
                position.original_quantity
            ),
            open_quantity=position.open_quantity,
            closed_quantity=(
                position.closed_quantity
            ),
            entry_price=position.entry_price,
            entry_order_status=(
                entry_order.status
            ),
            entry_filled_quantity=(
                entry_order.filled_quantity
            ),
            entry_average_fill_price=(
                entry_order.average_fill_price
            ),
            exit_order_count=len(
                exit_orders
            ),
            exit_fill_count=exit_fill_count,
            exit_filled_quantity=(
                exit_filled_quantity
            ),
            average_exit_price=(
                average_exit_price
            ),
            realized_pnl=position.realized_pnl,
            latest_unrealized_pnl=(
                latest_unrealized_pnl
            ),
            latest_total_pnl=latest_total_pnl,
            latest_ltp=latest_ltp,
            latest_pnl_at=latest_pnl_at,
            state=position.state,
            opened_at=position.opened_at,
            closed_at=position.closed_at,
            exit_persistence_in_sync=(
                exit_filled_quantity
                == position.closed_quantity
            ),
        )

    def _exit_fill_totals(
        self,
        exit_orders: tuple[
            OrderRecord,
            ...,
        ],
    ) -> tuple[
        int,
        int,
        float,
    ]:
        fill_count = 0
        quantity = 0
        notional = 0.0

        for order in exit_orders:
            fills = (
                self._order_fill_repository
                .list_by_order(
                    order.order_intent_id
                )
            )

            for fill in fills:
                self._validate_exit_fill(
                    order=order,
                    fill=fill,
                )

                fill_count += 1
                quantity += fill.quantity
                notional += (
                    fill.quantity
                    * fill.price
                )

        return (
            fill_count,
            quantity,
            notional,
        )

    @staticmethod
    def _validate_exit_fill(
        *,
        order: OrderRecord,
        fill: OrderFillRecord,
    ) -> None:
        if (
            fill.order_intent_id
            != order.order_intent_id
        ):
            raise TradeJournalIntegrityError(
                "OrderFillRecord does not match "
                "its requested SELL OrderRecord"
            )

        if fill.quantity <= 0:
            raise TradeJournalIntegrityError(
                "exit fill quantity must be positive"
            )

        if fill.price <= 0:
            raise TradeJournalIntegrityError(
                "exit fill price must be positive"
            )

    def _latest_pnl(
        self,
        position_id: str,
    ) -> PnLSnapshotRecord | None:
        snapshots = tuple(
            self._pnl_repository.list_by_position(
                position_id
            )
        )

        if not snapshots:
            return None

        return max(
            snapshots,
            key=lambda snapshot:
                snapshot.captured_at,
        )

    @staticmethod
    def _normalize_runtime_id(
        runtime_id: str,
    ) -> str:
        if not isinstance(
            runtime_id,
            str,
        ):
            raise TypeError(
                "runtime_id must be str"
            )

        normalized = runtime_id.strip()

        if not normalized:
            raise ValueError(
                "runtime_id cannot be empty"
            )

        return normalized


__all__ = [
    "TradeJournalIntegrityError",
    "TradeJournalService",
]
