"""
Phoenix M08 SQLAlchemy repository implementations.

Responsibilities:
    - CRUD operations
    - explicit persistence boundaries
    - runtime recovery queries
    - open-order queries
    - open-position queries
    - historical P&L/risk lookup
    - audit lookup

Repositories never own business rules.

Business logic remains in M03-M07.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.trading_control import TradingControlRecordData

from datetime import date
from typing import (
    Generic,
    TypeVar,
)

from sqlalchemy import (
    Select,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
)

from src.database.schema import (
    AuditEventRecord,
    OptionSelectionRecord,
    OrderFillRecord,
    OrderRecord,
    PnLSnapshotRecord,
    PositionRecord,
    RiskSnapshotRecord,
    RuntimeSessionRecord,
    SignalRecord,
    AccountEligibilitySnapshotRecord,
    AccountFundSnapshotRecord,
    AccountHealthSnapshotRecord,
    BrokerAccountRecord,
    BrokerConnectivitySnapshotRecord,
    BrokerSessionRecord,
    TenantRecord,
    UserBrokerAccountMembershipRecord,
    UserPasswordCredentialRecord,
    UserRecord,
)
from src.database.session import (
    DatabaseSessionManager,
)


RecordT = TypeVar(
    "RecordT",
    bound=DeclarativeBase,
)


class RepositoryRecordNotFoundError(
    KeyError
):
    """
    Requested persistence record does not exist.
    """


class DuplicateRepositoryRecordError(
    ValueError
):
    """
    Repository was asked to add an identity that already exists.
    """


class SQLAlchemyRepository(
    Generic[RecordT],
):
    """
    Base SQLAlchemy repository.

    Concrete repositories specify:
        model
        primary_key_attribute
    """

    model: type[RecordT]

    primary_key_attribute: str

    def __init__(
        self,
        *,
        sessions: DatabaseSessionManager,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record: RecordT,
    ) -> RecordT:
        """
        Persist a new record.

        Duplicate primary-key identities are rejected explicitly
        rather than relying on the later database exception.
        """

        identity = self._identity_from_record(
            record
        )

        with self._sessions.session_scope() as session:
            existing = session.get(
                self.model,
                identity,
            )

            if existing is not None:
                raise DuplicateRepositoryRecordError(
                    f"{self.model.__name__} "
                    f"already exists: {identity}"
                )

            session.add(
                record
            )

            session.flush()

            # Detach before Session closes so repository callers
            # may safely inspect the returned persistence record.
            session.expunge(
                record
            )

        return record

    def get(
        self,
        identity: str,
    ) -> RecordT | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                self.model,
                identity,
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def require(
        self,
        identity: str,
    ) -> RecordT:
        record = self.get(
            identity
        )

        if record is None:
            raise RepositoryRecordNotFoundError(
                f"{self.model.__name__} "
                f"not found: {identity}"
            )

        return record

    def delete(
        self,
        identity: str,
    ) -> bool:
        with self._sessions.session_scope() as session:
            record = session.get(
                self.model,
                identity,
            )

            if record is None:
                return False

            session.delete(
                record
            )

        return True

    def update(
        self,
        record: RecordT,
    ) -> RecordT:
        """
        Replace/update an existing ORM record.

        Intended for mutable persistence state such as:
            runtime state
            order state
            position state

        Business validation must have occurred before this layer.
        """

        identity = self._identity_from_record(
            record
        )

        with self._sessions.session_scope() as session:
            existing = session.get(
                self.model,
                identity,
            )

            if existing is None:
                raise RepositoryRecordNotFoundError(
                    f"{self.model.__name__} "
                    f"not found: {identity}"
                )

            merged = session.merge(
                record
            )

            session.flush()

            session.expunge(
                merged
            )

            return merged

    def _identity_from_record(
        self,
        record: RecordT,
    ) -> str:
        value = getattr(
            record,
            self.primary_key_attribute,
        )

        if not value:
            raise ValueError(
                "repository record identity "
                "cannot be empty"
            )

        return str(
            value
        )

    def _all(
        self,
        statement: Select,
    ) -> tuple[RecordT, ...]:
        with self._sessions.session_scope() as session:
            records = tuple(
                session.scalars(
                    statement
                ).all()
            )

            for record in records:
                session.expunge(
                    record
                )

            return records

    def _first(
        self,
        statement: Select,
    ) -> RecordT | None:
        with self._sessions.session_scope() as session:
            record = session.scalars(
                statement
            ).first()

            if record is None:
                return None

            session.expunge(
                record
            )

            return record


# ============================================================
# Runtime repository
# ============================================================


class SQLAlchemyRuntimeSessionRepository(
    SQLAlchemyRepository[
        RuntimeSessionRecord
    ],
):
    model = RuntimeSessionRecord
    primary_key_attribute = "runtime_id"

    def latest(
        self,
    ) -> RuntimeSessionRecord | None:
        return self._first(
            select(
                RuntimeSessionRecord
            )
            .order_by(
                RuntimeSessionRecord
                .updated_at
                .desc()
            )
        )

    def latest_for_trading_date(
        self,
        trading_date: date,
    ) -> RuntimeSessionRecord | None:
        return self._first(
            select(
                RuntimeSessionRecord
            )
            .where(
                RuntimeSessionRecord
                .trading_date
                == trading_date
            )
            .order_by(
                RuntimeSessionRecord
                .updated_at
                .desc()
            )
        )


# ============================================================
# Signal repository
# ============================================================


class SQLAlchemySignalRepository(
    SQLAlchemyRepository[
        SignalRecord
    ],
):
    model = SignalRecord
    primary_key_attribute = "signal_id"

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        SignalRecord,
        ...
    ]:
        return self._all(
            select(
                SignalRecord
            )
            .where(
                SignalRecord.runtime_id
                == runtime_id
            )
            .order_by(
                SignalRecord.created_at
            )
        )


# ============================================================
# Option Selection repository
# ============================================================


class SQLAlchemyOptionSelectionRepository(
    SQLAlchemyRepository[
        OptionSelectionRecord
    ],
):
    model = OptionSelectionRecord
    primary_key_attribute = (
        "selection_id"
    )

    def get_by_signal(
        self,
        signal_id: str,
    ) -> OptionSelectionRecord | None:
        return self._first(
            select(
                OptionSelectionRecord
            )
            .where(
                OptionSelectionRecord
                .signal_id
                == signal_id
            )
        )


# ============================================================
# Order repository
# ============================================================


class SQLAlchemyOrderRepository(
    SQLAlchemyRepository[
        OrderRecord
    ],
):
    model = OrderRecord
    primary_key_attribute = (
        "order_intent_id"
    )

    _TERMINAL_STATUSES = (
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "FAILED",
    )

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...
    ]:
        return self._all(
            select(
                OrderRecord
            )
            .where(
                OrderRecord.runtime_id
                == runtime_id
            )
            .order_by(
                OrderRecord.created_at
            )
        )

    def list_open_orders(
        self,
        runtime_id: str,
    ) -> tuple[
        OrderRecord,
        ...
    ]:
        """
        Recovery-oriented query.

        Any non-terminal order must be inspected/reconciled
        before Phoenix assumes execution state.
        """

        return self._all(
            select(
                OrderRecord
            )
            .where(
                OrderRecord.runtime_id
                == runtime_id
            )
            .where(
                OrderRecord.status.not_in(
                    self._TERMINAL_STATUSES
                )
            )
            .order_by(
                OrderRecord.updated_at
            )
        )

    def list_open_orders_for_position(
        self,
        position_id: str,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        """
        Return unresolved orders for one durable position
        across runtime boundaries.

        This is intentionally NOT scoped to runtime_id.

        A SELL submitted by an interrupted source runtime
        remains authoritative after Phoenix starts a new
        process/runtime and must still block duplicate exits.
        """

        if not isinstance(
            position_id,
            str,
        ):
            raise TypeError(
                "position_id must be a string"
            )

        normalized = position_id.strip()

        if not normalized:
            raise ValueError(
                "position_id cannot be empty"
            )

        return self._all(
            select(
                OrderRecord
            )
            .where(
                OrderRecord.position_id
                == normalized
            )
            .where(
                OrderRecord.status.not_in(
                    self._TERMINAL_STATUSES
                )
            )
            .order_by(
                OrderRecord.updated_at
            )
        )


    def list_by_trading_date(
        self,
        trading_date: date,
    ) -> tuple[
        OrderRecord,
        ...,
    ]:
        """
        Return every durable order intent consumed on one
        trading date across all Phoenix runtime processes.

        Terminal orders are intentionally included because
        they have already consumed ORD-/EXIT- sequence IDs.
        """

        if type(trading_date) is not date:
            raise TypeError(
                "trading_date must be a date"
            )

        return self._all(
            select(
                OrderRecord
            )
            .join(
                RuntimeSessionRecord,
                (
                    RuntimeSessionRecord.runtime_id
                    == OrderRecord.runtime_id
                ),
            )
            .where(
                RuntimeSessionRecord.trading_date
                == trading_date
            )
            .order_by(
                OrderRecord.created_at
            )
        )

    def get_by_broker_order_id(
        self,
        broker_order_id: str,
    ) -> OrderRecord | None:
        return self._first(
            select(
                OrderRecord
            )
            .where(
                OrderRecord
                .broker_order_id
                == broker_order_id
            )
        )


# ============================================================
# Fill repository
# ============================================================


class SQLAlchemyOrderFillRepository(
    SQLAlchemyRepository[
        OrderFillRecord
    ],
):
    model = OrderFillRecord
    primary_key_attribute = "fill_id"

    def list_by_order(
        self,
        order_intent_id: str,
    ) -> tuple[
        OrderFillRecord,
        ...
    ]:
        return self._all(
            select(
                OrderFillRecord
            )
            .where(
                OrderFillRecord
                .order_intent_id
                == order_intent_id
            )
            .order_by(
                OrderFillRecord.filled_at
            )
        )


# ============================================================
# Position repository
# ============================================================


class SQLAlchemyPositionRepository(
    SQLAlchemyRepository[
        PositionRecord
    ],
):
    model = PositionRecord
    primary_key_attribute = "position_id"

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        PositionRecord,
        ...
    ]:
        return self._all(
            select(
                PositionRecord
            )
            .where(
                PositionRecord.runtime_id
                == runtime_id
            )
            .order_by(
                PositionRecord.opened_at
            )
        )

    def get_by_entry_order_intent_id(
        self,
        entry_order_intent_id: str,
    ) -> PositionRecord | None:
        """
        Resolve the durable M07 position created from one BUY.

        Used by startup recovery to prove a broker FILLED BUY
        already crossed the PositionRecord durability boundary.
        """

        normalized = (
            entry_order_intent_id.strip()
        )

        if not normalized:
            raise ValueError(
                "entry_order_intent_id cannot be empty"
            )

        return self._first(
            select(
                PositionRecord
            )
            .where(
                PositionRecord
                .entry_order_intent_id
                == normalized
            )
        )

    def list_open_positions(
        self,
        runtime_id: str,
    ) -> tuple[
        PositionRecord,
        ...
    ]:
        """
        Quantity is authoritative for actual remaining exposure.

        State is intentionally not used as the sole filter.
        """

        return self._all(
            select(
                PositionRecord
            )
            .where(
                PositionRecord.runtime_id
                == runtime_id
            )
            .where(
                PositionRecord.open_quantity
                > 0
            )
            .order_by(
                PositionRecord.opened_at
            )
        )


# ============================================================
# P&L repository
# ============================================================


class SQLAlchemyPnLSnapshotRepository(
    SQLAlchemyRepository[
        PnLSnapshotRecord
    ],
):
    model = PnLSnapshotRecord
    primary_key_attribute = (
        "snapshot_id"
    )

    def list_by_position(
        self,
        position_id: str,
    ) -> tuple[
        PnLSnapshotRecord,
        ...
    ]:
        return self._all(
            select(
                PnLSnapshotRecord
            )
            .where(
                PnLSnapshotRecord.position_id
                == position_id
            )
            .order_by(
                PnLSnapshotRecord.captured_at
            )
        )

    def latest_for_position(
        self,
        position_id: str,
    ) -> PnLSnapshotRecord | None:
        return self._first(
            select(
                PnLSnapshotRecord
            )
            .where(
                PnLSnapshotRecord.position_id
                == position_id
            )
            .order_by(
                PnLSnapshotRecord
                .captured_at
                .desc()
            )
        )


# ============================================================
# Risk repository
# ============================================================


class SQLAlchemyRiskSnapshotRepository(
    SQLAlchemyRepository[
        RiskSnapshotRecord
    ],
):
    model = RiskSnapshotRecord
    primary_key_attribute = (
        "snapshot_id"
    )

    def latest_for_runtime(
        self,
        runtime_id: str,
    ) -> RiskSnapshotRecord | None:
        return self._first(
            select(
                RiskSnapshotRecord
            )
            .where(
                RiskSnapshotRecord.runtime_id
                == runtime_id
            )
            .order_by(
                RiskSnapshotRecord
                .captured_at
                .desc()
            )
        )


from datetime import datetime as TradingControlDateTime
from src.database.schema import TradingControlRecord


class SQLAlchemyTradingControlRepository(
    SQLAlchemyRepository[
        TradingControlRecord
    ],
):
    """
    Durable account-scoped M10 trading-control repository.

    ORM records remain private to this infrastructure adapter.
    Public methods return immutable TradingControlRecordData.
    """

    model = TradingControlRecord

    primary_key_attribute = (
        "control_id"
    )

    @staticmethod
    def _to_data(
        record: TradingControlRecord,
    ) -> "TradingControlRecordData":
        from src.app.trading_control import (
            TradingControlRecordData,
        )

        return TradingControlRecordData(
            control_id=record.control_id,
            broker=record.broker,
            account_id=record.account_id,
            state=record.state,
            changed_at=record.changed_at,
            message=record.message,
        )

    def get_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> "TradingControlRecordData | None":
        record = self._first(
            select(
                TradingControlRecord
            )
            .where(
                TradingControlRecord.broker
                == broker
            )
            .where(
                TradingControlRecord.account_id
                == account_id
            )
        )

        if record is None:
            return None

        return self._to_data(
            record
        )

    def set_for_account(
        self,
        *,
        broker: str,
        account_id: str,
        state: str,
        message: str | None,
        changed_at: TradingControlDateTime,
    ) -> "TradingControlRecordData":
        resolved_broker = broker.strip()
        resolved_account_id = account_id.strip()

        if not resolved_broker:
            raise ValueError(
                "broker cannot be empty"
            )

        if not resolved_account_id:
            raise ValueError(
                "account_id cannot be empty"
            )

        if state not in {
            "ACTIVE",
            "EXIT_AND_STOP",
        }:
            raise ValueError(
                "unsupported trading-control state"
            )

        if (
            message is not None
            and not message.strip()
        ):
            raise ValueError(
                "message cannot be empty"
            )

        if type(changed_at) is not TradingControlDateTime:
            raise TypeError(
                "changed_at must be datetime"
            )

        existing = self.get_for_account(
            broker=resolved_broker,
            account_id=resolved_account_id,
        )

        control_id = (
            existing.control_id
            if existing is not None
            else (
                f"{resolved_broker}:"
                f"{resolved_account_id}"
            )
        )

        record = TradingControlRecord(
            control_id=control_id,
            broker=resolved_broker,
            account_id=resolved_account_id,
            state=state,
            message=(
                message.strip()
                if message is not None
                else None
            ),
            changed_at=changed_at,
        )

        persisted = (
            self.add(record)
            if existing is None
            else self.update(record)
        )

        return self._to_data(
            persisted
        )



# ============================================================
# Audit repository
# ============================================================


class SQLAlchemyAuditEventRepository(
    SQLAlchemyRepository[
        AuditEventRecord
    ],
):
    model = AuditEventRecord
    primary_key_attribute = "event_id"

    def list_by_runtime(
        self,
        runtime_id: str,
    ) -> tuple[
        AuditEventRecord,
        ...
    ]:
        return self._all(
            select(
                AuditEventRecord
            )
            .where(
                AuditEventRecord.runtime_id
                == runtime_id
            )
            .order_by(
                AuditEventRecord.occurred_at
            )
        )

    def list_by_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> tuple[
        AuditEventRecord,
        ...
    ]:
        return self._all(
            select(
                AuditEventRecord
            )
            .where(
                AuditEventRecord.entity_type
                == entity_type
            )
            .where(
                AuditEventRecord.entity_id
                == entity_id
            )
            .order_by(
                AuditEventRecord.occurred_at
            )
        )

# ============================================================
# M09 Broker / Account repositories
# ============================================================


class SQLAlchemyBrokerAccountRepository:
    def __init__(
        self,
        *,
        sessions,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record: BrokerAccountRecord,
    ) -> BrokerAccountRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> BrokerAccountRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                BrokerAccountRecord,
                {
                    "broker": broker,
                    "account_id": account_id,
                },
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def require(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> BrokerAccountRecord:
        record = self.get(
            broker=broker,
            account_id=account_id,
        )

        if record is None:
            raise KeyError(
                "broker account not found: "
                f"{broker}:{account_id}"
            )

        return record

    def update(
        self,
        record: BrokerAccountRecord,
    ) -> BrokerAccountRecord:
        with self._sessions.session_scope() as session:
            merged = session.merge(
                record
            )

            session.flush()

            session.expunge(
                merged
            )

            return merged

    def list_all(
        self,
    ) -> tuple[
        BrokerAccountRecord,
        ...
    ]:
        with self._sessions.session_scope() as session:
            records = (
                session.query(
                    BrokerAccountRecord
                )
                .order_by(
                    BrokerAccountRecord.broker,
                    BrokerAccountRecord.account_id,
                )
                .all()
            )

            for record in records:
                session.expunge(
                    record
                )

            return tuple(
                records
            )


class SQLAlchemyBrokerSessionRepository:
    def __init__(
        self,
        *,
        sessions,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record: BrokerSessionRecord,
    ) -> BrokerSessionRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        session_id: str,
    ) -> BrokerSessionRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                BrokerSessionRecord,
                session_id,
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def require(
        self,
        session_id: str,
    ) -> BrokerSessionRecord:
        record = self.get(
            session_id
        )

        if record is None:
            raise KeyError(
                "broker session not found: "
                f"{session_id}"
            )

        return record

    def list_by_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> tuple[
        BrokerSessionRecord,
        ...
    ]:
        with self._sessions.session_scope() as session:
            records = (
                session.query(
                    BrokerSessionRecord
                )
                .filter(
                    BrokerSessionRecord.broker
                    == broker,
                    BrokerSessionRecord.account_id
                    == account_id,
                )
                .order_by(
                    BrokerSessionRecord.updated_at
                )
                .all()
            )

            for record in records:
                session.expunge(
                    record
                )

            return tuple(
                records
            )

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> BrokerSessionRecord | None:
        with self._sessions.session_scope() as session:
            record = (
                session.query(
                    BrokerSessionRecord
                )
                .filter(
                    BrokerSessionRecord.broker
                    == broker,
                    BrokerSessionRecord.account_id
                    == account_id,
                )
                .order_by(
                    BrokerSessionRecord.updated_at.desc()
                )
                .first()
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record


class SQLAlchemyAccountFundSnapshotRepository:
    def __init__(
        self,
        *,
        sessions,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record: AccountFundSnapshotRecord,
    ) -> AccountFundSnapshotRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        snapshot_id: str,
    ) -> AccountFundSnapshotRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                AccountFundSnapshotRecord,
                snapshot_id,
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def require(
        self,
        snapshot_id: str,
    ) -> AccountFundSnapshotRecord:
        record = self.get(
            snapshot_id
        )

        if record is None:
            raise KeyError(
                "account funds snapshot not found: "
                f"{snapshot_id}"
            )

        return record

    def list_by_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> tuple[
        AccountFundSnapshotRecord,
        ...
    ]:
        with self._sessions.session_scope() as session:
            records = (
                session.query(
                    AccountFundSnapshotRecord
                )
                .filter(
                    AccountFundSnapshotRecord.broker
                    == broker,
                    AccountFundSnapshotRecord.account_id
                    == account_id,
                )
                .order_by(
                    AccountFundSnapshotRecord.fetched_at
                )
                .all()
            )

            for record in records:
                session.expunge(
                    record
                )

            return tuple(
                records
            )

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> AccountFundSnapshotRecord | None:
        with self._sessions.session_scope() as session:
            record = (
                session.query(
                    AccountFundSnapshotRecord
                )
                .filter(
                    AccountFundSnapshotRecord.broker
                    == broker,
                    AccountFundSnapshotRecord.account_id
                    == account_id,
                )
                .order_by(
                    AccountFundSnapshotRecord.fetched_at.desc()
                )
                .first()
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record


class SQLAlchemyBrokerConnectivitySnapshotRepository:
    def __init__(
        self,
        *,
        sessions,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record:
            BrokerConnectivitySnapshotRecord,
    ) -> BrokerConnectivitySnapshotRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        snapshot_id: str,
    ) -> BrokerConnectivitySnapshotRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                BrokerConnectivitySnapshotRecord,
                snapshot_id,
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> BrokerConnectivitySnapshotRecord | None:
        with self._sessions.session_scope() as session:
            record = (
                session.query(
                    BrokerConnectivitySnapshotRecord
                )
                .filter(
                    BrokerConnectivitySnapshotRecord.broker
                    == broker,
                    BrokerConnectivitySnapshotRecord.account_id
                    == account_id,
                )
                .order_by(
                    BrokerConnectivitySnapshotRecord
                    .checked_at.desc()
                )
                .first()
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record


class SQLAlchemyAccountHealthSnapshotRepository:
    def __init__(
        self,
        *,
        sessions,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record: AccountHealthSnapshotRecord,
    ) -> AccountHealthSnapshotRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        snapshot_id: str,
    ) -> AccountHealthSnapshotRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                AccountHealthSnapshotRecord,
                snapshot_id,
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> AccountHealthSnapshotRecord | None:
        with self._sessions.session_scope() as session:
            record = (
                session.query(
                    AccountHealthSnapshotRecord
                )
                .filter(
                    AccountHealthSnapshotRecord.broker
                    == broker,
                    AccountHealthSnapshotRecord.account_id
                    == account_id,
                )
                .order_by(
                    AccountHealthSnapshotRecord
                    .checked_at.desc()
                )
                .first()
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record


class SQLAlchemyAccountEligibilitySnapshotRepository:
    def __init__(
        self,
        *,
        sessions,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record:
            AccountEligibilitySnapshotRecord,
    ) -> AccountEligibilitySnapshotRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        snapshot_id: str,
    ) -> AccountEligibilitySnapshotRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                AccountEligibilitySnapshotRecord,
                snapshot_id,
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> AccountEligibilitySnapshotRecord | None:
        with self._sessions.session_scope() as session:
            record = (
                session.query(
                    AccountEligibilitySnapshotRecord
                )
                .filter(
                    AccountEligibilitySnapshotRecord.broker
                    == broker,
                    AccountEligibilitySnapshotRecord.account_id
                    == account_id,
                )
                .order_by(
                    AccountEligibilitySnapshotRecord
                    .evaluated_at.desc()
                )
                .first()
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record


# ============================================================
# M15 Tenant / User / Account membership repositories
# ============================================================


class SQLAlchemyTenantRepository:
    def __init__(
        self,
        *,
        sessions: DatabaseSessionManager,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record: TenantRecord,
    ) -> TenantRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        tenant_id: str,
    ) -> TenantRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                TenantRecord,
                tenant_id,
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def require(
        self,
        tenant_id: str,
    ) -> TenantRecord:
        record = self.get(
            tenant_id
        )

        if record is None:
            raise KeyError(
                "tenant not found: "
                f"{tenant_id}"
            )

        return record

    def update(
        self,
        record: TenantRecord,
    ) -> TenantRecord:
        with self._sessions.session_scope() as session:
            merged = session.merge(
                record
            )

            session.flush()

            session.expunge(
                merged
            )

            return merged

    def list_all(
        self,
    ) -> tuple[
        TenantRecord,
        ...
    ]:
        with self._sessions.session_scope() as session:
            records = (
                session.query(
                    TenantRecord
                )
                .order_by(
                    TenantRecord.tenant_id
                )
                .all()
            )

            for record in records:
                session.expunge(
                    record
                )

            return tuple(
                records
            )


class SQLAlchemyUserRepository:
    def __init__(
        self,
        *,
        sessions: DatabaseSessionManager,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record: UserRecord,
    ) -> UserRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> UserRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                UserRecord,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def require(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> UserRecord:
        record = self.get(
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if record is None:
            raise KeyError(
                "user not found: "
                f"{tenant_id}:{user_id}"
            )

        return record

    def update(
        self,
        record: UserRecord,
    ) -> UserRecord:
        with self._sessions.session_scope() as session:
            merged = session.merge(
                record
            )

            session.flush()

            session.expunge(
                merged
            )

            return merged

    def list_for_tenant(
        self,
        tenant_id: str,
    ) -> tuple[
        UserRecord,
        ...
    ]:
        with self._sessions.session_scope() as session:
            records = (
                session.query(
                    UserRecord
                )
                .filter(
                    UserRecord.tenant_id
                    == tenant_id
                )
                .order_by(
                    UserRecord.user_id
                )
                .all()
            )

            for record in records:
                session.expunge(
                    record
                )

            return tuple(
                records
            )


class SQLAlchemyUserPasswordCredentialRepository:
    def __init__(
        self,
        *,
        sessions: DatabaseSessionManager,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record: UserPasswordCredentialRecord,
    ) -> UserPasswordCredentialRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> UserPasswordCredentialRecord | None:
        with self._sessions.session_scope() as session:
            record = session.get(
                UserPasswordCredentialRecord,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def require(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> UserPasswordCredentialRecord:
        record = self.get(
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if record is None:
            raise KeyError(
                "user password credential not found: "
                f"{tenant_id}:{user_id}"
            )

        return record

    def update(
        self,
        record: UserPasswordCredentialRecord,
    ) -> UserPasswordCredentialRecord:
        with self._sessions.session_scope() as session:
            merged = session.merge(
                record
            )

            session.flush()

            session.expunge(
                merged
            )

            return merged


class SQLAlchemyUserBrokerAccountMembershipRepository:
    def __init__(
        self,
        *,
        sessions: DatabaseSessionManager,
    ) -> None:
        self._sessions = sessions

    def add(
        self,
        record:
            UserBrokerAccountMembershipRecord,
    ) -> UserBrokerAccountMembershipRecord:
        with self._sessions.session_scope() as session:
            session.add(
                record
            )

        return record

    def get(
        self,
        *,
        tenant_id: str,
        user_id: str,
        broker: str,
        account_id: str,
    ) -> (
        UserBrokerAccountMembershipRecord
        | None
    ):
        with self._sessions.session_scope() as session:
            record = session.get(
                UserBrokerAccountMembershipRecord,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "broker": broker,
                    "account_id": account_id,
                },
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def get_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> (
        UserBrokerAccountMembershipRecord
        | None
    ):
        with self._sessions.session_scope() as session:
            record = (
                session.query(
                    UserBrokerAccountMembershipRecord
                )
                .filter(
                    UserBrokerAccountMembershipRecord.broker
                    == broker,
                    UserBrokerAccountMembershipRecord.account_id
                    == account_id,
                )
                .one_or_none()
            )

            if record is None:
                return None

            session.expunge(
                record
            )

            return record

    def list_for_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> tuple[
        UserBrokerAccountMembershipRecord,
        ...
    ]:
        with self._sessions.session_scope() as session:
            records = (
                session.query(
                    UserBrokerAccountMembershipRecord
                )
                .filter(
                    UserBrokerAccountMembershipRecord.tenant_id
                    == tenant_id,
                    UserBrokerAccountMembershipRecord.user_id
                    == user_id,
                )
                .order_by(
                    UserBrokerAccountMembershipRecord.broker,
                    UserBrokerAccountMembershipRecord.account_id,
                )
                .all()
            )

            for record in records:
                session.expunge(
                    record
                )

            return tuple(
                records
            )

    def remove(
        self,
        *,
        tenant_id: str,
        user_id: str,
        broker: str,
        account_id: str,
    ) -> bool:
        with self._sessions.session_scope() as session:
            record = session.get(
                UserBrokerAccountMembershipRecord,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "broker": broker,
                    "account_id": account_id,
                },
            )

            if record is None:
                return False

            session.delete(
                record
            )

            return True
