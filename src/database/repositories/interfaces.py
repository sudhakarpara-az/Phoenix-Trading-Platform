"""
Phoenix M08 repository interfaces.

These protocols define the persistence capabilities required
by the Phoenix runtime.

No SQLAlchemy imports belong in this module.
"""

from __future__ import annotations

from typing import (
    Protocol,
    TypeVar,
)


T = TypeVar("T")


class Repository(
    Protocol[T],
):
    def add(
        self,
        record: T,
    ) -> T:
        ...

    def get(
        self,
        identity: str,
    ) -> T | None:
        ...

    def require(
        self,
        identity: str,
    ) -> T:
        ...

    def delete(
        self,
        identity: str,
    ) -> bool:
        ...


class RuntimeSessionRepository(
    Repository[T],
    Protocol[T],
):
    def latest(
        self,
    ) -> T | None:
        ...

    def latest_for_trading_date(
        self,
        trading_date,
    ) -> T | None:
        ...


class SignalRepository(
    Repository[T],
    Protocol[T],
):
    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[T, ...]:
        ...


class OptionSelectionRepository(
    Repository[T],
    Protocol[T],
):
    def get_by_signal(
        self,
        signal_id: str,
    ) -> T | None:
        ...


class OrderRepository(
    Repository[T],
    Protocol[T],
):
    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[T, ...]:
        ...

    def list_open_orders(
        self,
        runtime_id: str,
    ) -> tuple[T, ...]:
        ...

    def get_by_broker_order_id(
        self,
        broker_order_id: str,
    ) -> T | None:
        ...


class OrderFillRepository(
    Repository[T],
    Protocol[T],
):
    def list_by_order(
        self,
        order_intent_id: str,
    ) -> tuple[T, ...]:
        ...


class PositionRepository(
    Repository[T],
    Protocol[T],
):
    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[T, ...]:
        ...

    def list_open_positions(
        self,
        runtime_id: str,
    ) -> tuple[T, ...]:
        ...


class PnLSnapshotRepository(
    Repository[T],
    Protocol[T],
):
    def list_by_position(
        self,
        position_id: str,
    ) -> tuple[T, ...]:
        ...

    def latest_for_position(
        self,
        position_id: str,
    ) -> T | None:
        ...


class RiskSnapshotRepository(
    Repository[T],
    Protocol[T],
):
    def latest_for_runtime(
        self,
        runtime_id: str,
    ) -> T | None:
        ...


class AuditEventRepository(
    Repository[T],
    Protocol[T],
):
    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[T, ...]:
        ...

    def list_by_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> tuple[T, ...]:
        ...