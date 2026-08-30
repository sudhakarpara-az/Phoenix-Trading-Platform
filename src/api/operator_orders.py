from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.api.operator_snapshot import (
    RuntimeSnapshotReader,
)
from src.database.schema import (
    OrderRecord,
)


class OperatorOrderRepositoryReader(
    Protocol,
):
    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        ...

    def list_open_orders(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorOrderView:
    order_intent_id: str
    runtime_id: str

    signal_id: str | None
    position_id: str | None

    security_id: str
    symbol: str

    side: str
    order_type: str
    reason: str | None

    quantity: int
    limit_price: float | None

    execution_mode: str
    status: str

    broker_name: str | None
    broker_order_id: str | None

    filled_quantity: int
    average_fill_price: float | None

    created_at: datetime
    submitted_at: datetime | None
    updated_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorOrdersView:
    runtime_id: str

    orders: tuple[
        OperatorOrderView,
        ...,
    ]

    open_orders: tuple[
        OperatorOrderView,
        ...,
    ]

    total_count: int
    open_count: int

    captured_at: datetime


class OperatorOrderService:
    """
    Passive M13 projection of durable M06 order state.

    Runtime identity remains owned by the existing runtime
    orchestrator.

    Order history and unresolved-order semantics remain owned
    by the existing durable order repository.

    M13 does not infer terminal states, reconcile brokers,
    transition orders, persist records, cancel orders, or
    submit orders.
    """

    def __init__(
        self,
        *,
        runtime: RuntimeSnapshotReader,
        order_repository: OperatorOrderRepositoryReader,
    ) -> None:
        self._runtime = runtime
        self._order_repository = (
            order_repository
        )

    @property
    def runtime(
        self,
    ) -> RuntimeSnapshotReader:
        return self._runtime

    @property
    def order_repository(
        self,
    ) -> OperatorOrderRepositoryReader:
        return self._order_repository

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorOrdersView:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be a datetime"
            )

        runtime = self._runtime.snapshot

        runtime_id = (
            runtime.runtime_id.value
        )

        orders = (
            self._order_repository
            .list_by_runtime(
                runtime_id
            )
        )

        open_orders = (
            self._order_repository
            .list_open_orders(
                runtime_id
            )
        )

        projected_orders = tuple(
            self._project(
                order
            )
            for order in orders
        )

        projected_open_orders = tuple(
            self._project(
                order
            )
            for order in open_orders
        )

        return OperatorOrdersView(
            runtime_id=runtime_id,
            orders=projected_orders,
            open_orders=(
                projected_open_orders
            ),
            total_count=len(
                projected_orders
            ),
            open_count=len(
                projected_open_orders
            ),
            captured_at=captured_at,
        )

    @staticmethod
    def _project(
        order: OrderRecord,
    ) -> OperatorOrderView:
        return OperatorOrderView(
            order_intent_id=(
                order.order_intent_id
            ),
            runtime_id=(
                order.runtime_id
            ),
            signal_id=(
                order.signal_id
            ),
            position_id=(
                order.position_id
            ),
            security_id=(
                order.security_id
            ),
            symbol=order.symbol,
            side=order.side,
            order_type=(
                order.order_type
            ),
            reason=order.reason,
            quantity=order.quantity,
            limit_price=(
                order.limit_price
            ),
            execution_mode=(
                order.execution_mode
            ),
            status=order.status,
            broker_name=(
                order.broker_name
            ),
            broker_order_id=(
                order.broker_order_id
            ),
            filled_quantity=(
                order.filled_quantity
            ),
            average_fill_price=(
                order.average_fill_price
            ),
            created_at=(
                order.created_at
            ),
            submitted_at=(
                order.submitted_at
            ),
            updated_at=(
                order.updated_at
            ),
        )


__all__ = [
    "OperatorOrderRepositoryReader",
    "OperatorOrderService",
    "OperatorOrderView",
    "OperatorOrdersView",
]
