"""
Phoenix M08 repository interfaces.

These protocols define the persistence capabilities required
by the Phoenix runtime.

No SQLAlchemy imports belong in this module.
"""
from typing import Protocol
from __future__ import annotations

from typing import (
    Protocol,
    TypeVar,
)
from src.database.schema import (
    AccountEligibilitySnapshotRecord,
    AccountFundSnapshotRecord,
    AccountHealthSnapshotRecord,
    BrokerAccountRecord,
    BrokerConnectivitySnapshotRecord,
    BrokerSessionRecord,
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

# ============================================================
# M09 Broker / Account repositories
# ============================================================


class BrokerAccountRepository(Protocol):
    def add(
        self,
        record: BrokerAccountRecord,
    ) -> BrokerAccountRecord:
        ...

    def get(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> BrokerAccountRecord | None:
        ...

    def require(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> BrokerAccountRecord:
        ...

    def update(
        self,
        record: BrokerAccountRecord,
    ) -> BrokerAccountRecord:
        ...

    def list_all(
        self,
    ) -> tuple[
        BrokerAccountRecord,
        ...
    ]:
        ...


class BrokerSessionRepository(Protocol):
    def add(
        self,
        record: BrokerSessionRecord,
    ) -> BrokerSessionRecord:
        ...

    def get(
        self,
        session_id: str,
    ) -> BrokerSessionRecord | None:
        ...

    def require(
        self,
        session_id: str,
    ) -> BrokerSessionRecord:
        ...

    def list_by_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> tuple[
        BrokerSessionRecord,
        ...
    ]:
        ...

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> BrokerSessionRecord | None:
        ...


class AccountFundSnapshotRepository(Protocol):
    def add(
        self,
        record: AccountFundSnapshotRecord,
    ) -> AccountFundSnapshotRecord:
        ...

    def get(
        self,
        snapshot_id: str,
    ) -> AccountFundSnapshotRecord | None:
        ...

    def require(
        self,
        snapshot_id: str,
    ) -> AccountFundSnapshotRecord:
        ...

    def list_by_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> tuple[
        AccountFundSnapshotRecord,
        ...
    ]:
        ...

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> AccountFundSnapshotRecord | None:
        ...


class BrokerConnectivitySnapshotRepository(Protocol):
    def add(
        self,
        record: BrokerConnectivitySnapshotRecord,
    ) -> BrokerConnectivitySnapshotRecord:
        ...

    def get(
        self,
        snapshot_id: str,
    ) -> BrokerConnectivitySnapshotRecord | None:
        ...

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> BrokerConnectivitySnapshotRecord | None:
        ...


class AccountHealthSnapshotRepository(Protocol):
    def add(
        self,
        record: AccountHealthSnapshotRecord,
    ) -> AccountHealthSnapshotRecord:
        ...

    def get(
        self,
        snapshot_id: str,
    ) -> AccountHealthSnapshotRecord | None:
        ...

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> AccountHealthSnapshotRecord | None:
        ...


class AccountEligibilitySnapshotRepository(Protocol):
    def add(
        self,
        record: AccountEligibilitySnapshotRecord,
    ) -> AccountEligibilitySnapshotRecord:
        ...

    def get(
        self,
        snapshot_id: str,
    ) -> AccountEligibilitySnapshotRecord | None:
        ...

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> AccountEligibilitySnapshotRecord | None:
        ...