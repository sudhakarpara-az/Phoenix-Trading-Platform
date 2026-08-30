"""
Phoenix M08 persistent database schema.

Defines durable relational storage for:

    - runtime sessions
    - strategy signals
    - option selections
    - broker orders
    - broker fills
    - managed positions
    - P&L snapshots
    - risk snapshots
    - audit events
    - M15 tenants and users
    - M15 user-to-broker-account memberships
    - M15 user password credentials

Important architectural rule:

    ORM persistence models are NOT Phoenix business-domain
    models.

Repositories introduced in M08-T04 will translate between
these persistence records and the existing M04-M08 domain
objects.

No repository logic or runtime orchestration belongs here.
"""

from __future__ import annotations
from decimal import Decimal
from datetime import (
    date,
    datetime,
)

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


# ------------------------------------------------------------
# Naming convention
#
# Explicit deterministic names make future schema migrations
# easier to reason about.
# ------------------------------------------------------------

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": (
        "fk_%(table_name)s_"
        "%(column_0_name)s_"
        "%(referred_table_name)s"
    ),
    "pk": "pk_%(table_name)s",
}


class Base(
    DeclarativeBase,
):
    metadata = MetaData(
        naming_convention=(
            NAMING_CONVENTION
        )
    )


# ============================================================
# Runtime Session
# ============================================================


class RuntimeSessionRecord(Base):
    """
    One Phoenix application runtime/session.

    Example runtime id:
        PHOENIX:2026-08-08:LIVE

    This record is central to restart/recovery in later M08
    tasks.
    """

    __tablename__ = "runtime_sessions"

    runtime_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    trading_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime,
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    stopped_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime,
        nullable=True,
    )

    recovery_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    recovered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    failure_code: Mapped[
        str | None
    ] = mapped_column(
        String(64),
        nullable=True,
    )

    failure_message: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    failure_component: Mapped[
        str | None
    ] = mapped_column(
        String(128),
        nullable=True,
    )

    failure_occurred_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime,
        nullable=True,
    )

    failure_recoverable: Mapped[
        bool | None
    ] = mapped_column(
        Boolean,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "mode IN ('DRY_RUN', 'LIVE')",
            name="valid_mode",
        ),
        CheckConstraint(
            """
            state IN (
                'CREATED',
                'STARTING',
                'RECOVERING',
                'READY',
                'RUNNING',
                'STOPPING',
                'STOPPED',
                'FAILED'
            )
            """,
            name="valid_state",
        ),
    )


# ============================================================
# Signal
# ============================================================


class SignalRecord(Base):
    """
    Durable M04 trading signal.
    """

    __tablename__ = "signals"

    signal_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    runtime_id: Mapped[str] = mapped_column(
        ForeignKey(
            "runtime_sessions.runtime_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    trading_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
    )

    signal_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    option_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )

    underlying_price: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="positive_quantity",
        ),
        CheckConstraint(
            "option_type IN ('CALL', 'PUT')",
            name="valid_option_type",
        ),
        Index(
            "ix_signals_runtime_level_date",
            "runtime_id",
            "level",
            "trading_date",
        ),
    )


# ============================================================
# Option Selection
# ============================================================


class OptionSelectionRecord(Base):
    """
    Durable M05 selected option contract.

    Security ID remains the broker/exchange contract identity.
    """

    __tablename__ = "option_selections"

    selection_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    runtime_id: Mapped[str] = mapped_column(
        ForeignKey(
            "runtime_sessions.runtime_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    signal_id: Mapped[str] = mapped_column(
        ForeignKey(
            "signals.signal_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    underlying_symbol: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    symbol: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    security_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    option_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )

    strike: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    expiry: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    lot_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    ltp: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    delta: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    target_delta: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    bid: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    ask: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    volume: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    open_interest: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    quote_received_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime,
        nullable=True,
    )

    selected_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "option_type IN ('CALL', 'PUT')",
            name="valid_option_type",
        ),
        CheckConstraint(
            "strike > 0",
            name="positive_strike",
        ),
        CheckConstraint(
            "lot_size > 0",
            name="positive_lot_size",
        ),
        CheckConstraint(
            "ltp > 0",
            name="positive_ltp",
        ),
        UniqueConstraint(
            "signal_id",
            name=(
                "uq_option_selections_signal"
            ),
        ),
    )


# ============================================================
# Orders
# ============================================================


class OrderRecord(Base):
    """
    Durable M06 order lifecycle.

    Stores both BUY and SELL intents/results.
    """

    __tablename__ = "orders"

    order_intent_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    runtime_id: Mapped[str] = mapped_column(
        ForeignKey(
            "runtime_sessions.runtime_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    signal_id: Mapped[
        str | None
    ] = mapped_column(
        ForeignKey(
            "signals.signal_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    position_id: Mapped[
        str | None
    ] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    security_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    symbol: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    side: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )

    order_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    reason: Mapped[
        str | None
    ] = mapped_column(
        String(64),
        nullable=True,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    limit_price: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    execution_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    broker_name: Mapped[
        str | None
    ] = mapped_column(
        String(32),
        nullable=True,
    )

    broker_order_id: Mapped[
        str | None
    ] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    filled_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    average_fill_price: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    submitted_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime,
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "side IN ('BUY', 'SELL')",
            name="valid_side",
        ),
        CheckConstraint(
            "order_type IN ('LIMIT', 'MARKET')",
            name="valid_order_type",
        ),
        CheckConstraint(
            "quantity > 0",
            name="positive_quantity",
        ),
        CheckConstraint(
            "filled_quantity >= 0",
            name="nonnegative_filled_quantity",
        ),
        CheckConstraint(
            "filled_quantity <= quantity",
            name="fill_not_over_quantity",
        ),
        CheckConstraint(
            "execution_mode IN ('DRY_RUN', 'LIVE')",
            name="valid_execution_mode",
        ),
        Index(
            "ix_orders_runtime_status",
            "runtime_id",
            "status",
        ),
    )


# ============================================================
# Order Fills
# ============================================================


class OrderFillRecord(Base):
    """
    Individual actual execution/fill.

    Multiple rows may belong to one order because an exchange
    order may fill in pieces.
    """

    __tablename__ = "order_fills"

    fill_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    order_intent_id: Mapped[str] = mapped_column(
        ForeignKey(
            "orders.order_intent_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    broker_trade_id: Mapped[
        str | None
    ] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    filled_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="positive_quantity",
        ),
        CheckConstraint(
            "price > 0",
            name="positive_price",
        ),
        UniqueConstraint(
            "order_intent_id",
            "broker_trade_id",
            name="uq_order_fill_broker_trade",
        ),
    )


# ============================================================
# Position
# ============================================================


class PositionRecord(Base):
    """
    Durable M06/M07 managed position state.

    The position_id is the existing FilledPositionId value.

    risk_id preserves the existing M07 PositionRiskId.
    """

    __tablename__ = "positions"

    position_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    risk_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )

    runtime_id: Mapped[str] = mapped_column(
        ForeignKey(
            "runtime_sessions.runtime_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    signal_id: Mapped[str] = mapped_column(
        ForeignKey(
            "signals.signal_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    entry_order_intent_id: Mapped[str] = mapped_column(
        ForeignKey(
            "orders.order_intent_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        unique=True,
    )

    security_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    symbol: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    option_type: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )

    level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
    )

    original_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    open_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    closed_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    entry_price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    realized_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )

    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    stop_price: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    stop_risk_points: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    stop_state: Mapped[
        str | None
    ] = mapped_column(
        String(32),
        nullable=True,
    )

    executable_target_price: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    mapped_target_price: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    booking_zone_start: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    booking_zone_end: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    target_state: Mapped[
        str | None
    ] = mapped_column(
        String(32),
        nullable=True,
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "option_type IN ('CALL', 'PUT')",
            name="valid_option_type",
        ),
        CheckConstraint(
            "original_quantity > 0",
            name="positive_original_quantity",
        ),
        CheckConstraint(
            "open_quantity >= 0",
            name="nonnegative_open_quantity",
        ),
        CheckConstraint(
            "closed_quantity >= 0",
            name="nonnegative_closed_quantity",
        ),
        CheckConstraint(
            """
            open_quantity + closed_quantity
            = original_quantity
            """,
            name="quantity_conservation",
        ),
        CheckConstraint(
            "entry_price > 0",
            name="positive_entry_price",
        ),
        Index(
            "ix_positions_runtime_state",
            "runtime_id",
            "state",
        ),
        Index(
            "ix_positions_runtime_level_state",
            "runtime_id",
            "level",
            "state",
        ),
    )


# ============================================================
# P&L Snapshot
# ============================================================


class PnLSnapshotRecord(Base):
    """
    Historical M07 P&L observation.

    These are snapshots rather than the source of truth for
    individual fills.
    """

    __tablename__ = "pnl_snapshots"

    snapshot_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    runtime_id: Mapped[str] = mapped_column(
        ForeignKey(
            "runtime_sessions.runtime_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    position_id: Mapped[str] = mapped_column(
        ForeignKey(
            "positions.position_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    realized_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    unrealized_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    total_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    unrealized_points: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    ltp: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    open_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    captured_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "open_quantity >= 0",
            name="nonnegative_open_quantity",
        ),
        Index(
            "ix_pnl_position_captured",
            "position_id",
            "captured_at",
        ),
    )


# ============================================================
# Risk Snapshot
# ============================================================


class RiskSnapshotRecord(Base):
    """
    Historical M07 aggregate/day-level risk snapshot.
    """

    __tablename__ = "risk_snapshots"

    snapshot_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    runtime_id: Mapped[str] = mapped_column(
        ForeignKey(
            "runtime_sessions.runtime_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    trading_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    realized_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    unrealized_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    total_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    open_positions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    closed_positions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    open_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    new_entries_allowed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    lock_reason: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    captured_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "open_positions >= 0",
            name="nonnegative_open_positions",
        ),
        CheckConstraint(
            "closed_positions >= 0",
            name="nonnegative_closed_positions",
        ),
        CheckConstraint(
            "open_quantity >= 0",
            name="nonnegative_open_quantity",
        ),
        Index(
            "ix_risk_runtime_captured",
            "runtime_id",
            "captured_at",
        ),
    )


class TradingControlRecord(Base):
    """
    Durable M10 account-level application control state.

    One record exists per broker/account identity.
    """

    __tablename__ = "trading_control_states"

    control_id: Mapped[str] = mapped_column(
        String(256),
        primary_key=True,
    )

    broker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )

    account_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )

    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    changed_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('ACTIVE', 'EXIT_AND_STOP')",
            name="valid_trading_control_state",
        ),
        Index(
            "ux_trading_control_account",
            "broker",
            "account_id",
            unique=True,
        ),
    )



# ============================================================
# Audit Event
# ============================================================


class AuditEventRecord(Base):
    """
    Append-oriented Phoenix operational audit event.

    Examples:
        SIGNAL_CREATED
        OPTION_SELECTED
        ORDER_SUBMITTED
        ORDER_FILLED
        POSITION_OPENED
        TARGET_TRIGGERED
        STOP_TRIGGERED
        POSITION_CLOSED
        RECOVERY_STARTED
        RECOVERY_COMPLETED

    payload is stored as text in T03 deliberately. T04/T05 may
    introduce a structured serialization boundary.
    """

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    runtime_id: Mapped[str] = mapped_column(
        ForeignKey(
            "runtime_sessions.runtime_id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    entity_type: Mapped[
        str | None
    ] = mapped_column(
        String(64),
        nullable=True,
    )

    entity_id: Mapped[
        str | None
    ] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    message: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    payload: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index(
            "ix_audit_entity",
            "entity_type",
            "entity_id",
        ),
    )


# ============================================================
# Schema lifecycle
# ============================================================


def create_schema(
    engine,
) -> None:
    """
    Create all registered Phoenix persistence tables.

    SQLAlchemy create_all() is idempotent for tables already
    present.

    Formal migrations will be introduced before production
    schema evolution.
    """

    Base.metadata.create_all(
        bind=engine
    )


def drop_schema(
    engine,
) -> None:
    """
    Drop all Phoenix tables.

    Intended for automated tests only.
    """

    Base.metadata.drop_all(
        bind=engine
    )

# ============================================================
# M09 Broker / Account persistence
# ============================================================


class BrokerAccountRecord(Base):
    """
    Current broker-account identity and latest profile state.

    Credentials, access tokens, passwords and TOTP secrets
    must never be stored here.
    """

    __tablename__ = "broker_accounts"

    broker: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
    )

    account_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    account_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    client_name: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )

    trading_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    product_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    profile_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "broker IN ('DHAN')",
            name="ck_broker_accounts_broker",
        ),
        CheckConstraint(
            "account_status IN "
            "('UNKNOWN', 'ACTIVE', 'INACTIVE', 'BLOCKED')",
            name="ck_broker_accounts_status",
        ),
    )


class BrokerSessionRecord(Base):
    """
    Historical broker-session state snapshot.

    No authentication secret or token is persisted.
    """

    __tablename__ = "broker_sessions"

    session_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    broker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    authenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    failure_message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker", "account_id"],
            [
                "broker_accounts.broker",
                "broker_accounts.account_id",
            ],
            ondelete="CASCADE",
            name="fk_broker_sessions_account",
        ),
        CheckConstraint(
            "status IN ("
            "'NOT_INITIALIZED', "
            "'AUTHENTICATING', "
            "'AUTHENTICATED', "
            "'EXPIRED', "
            "'FAILED', "
            "'CLOSED'"
            ")",
            name="ck_broker_sessions_status",
        ),
    )


class AccountFundSnapshotRecord(Base):
    """
    Historical funds / margin snapshot.
    """

    __tablename__ = "account_fund_snapshots"

    snapshot_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    broker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    available_cash: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    available_margin: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    utilized_margin: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    collateral: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )

    opening_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker", "account_id"],
            [
                "broker_accounts.broker",
                "broker_accounts.account_id",
            ],
            ondelete="CASCADE",
            name="fk_account_funds_account",
        ),
        CheckConstraint(
            "available_cash >= 0",
            name="ck_account_funds_cash_nonnegative",
        ),
        CheckConstraint(
            "available_margin >= 0",
            name="ck_account_funds_margin_nonnegative",
        ),
        CheckConstraint(
            "utilized_margin >= 0",
            name="ck_account_funds_utilized_nonnegative",
        ),
        CheckConstraint(
            "collateral >= 0",
            name="ck_account_funds_collateral_nonnegative",
        ),
        CheckConstraint(
            "opening_balance IS NULL "
            "OR opening_balance >= 0",
            name="ck_account_funds_opening_nonnegative",
        ),
    )


class BrokerConnectivitySnapshotRecord(Base):
    """
    Historical broker connectivity state.
    """

    __tablename__ = "broker_connectivity_snapshots"

    snapshot_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    broker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    connected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    checked_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    latency_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker", "account_id"],
            [
                "broker_accounts.broker",
                "broker_accounts.account_id",
            ],
            ondelete="CASCADE",
            name="fk_broker_connectivity_account",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_broker_connectivity_latency",
        ),
    )


class AccountHealthSnapshotRecord(Base):
    """
    Historical aggregate account-health state.
    """

    __tablename__ = "account_health_snapshots"

    snapshot_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    broker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    checked_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    broker_connected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    session_authenticated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    profile_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    funds_available: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker", "account_id"],
            [
                "broker_accounts.broker",
                "broker_accounts.account_id",
            ],
            ondelete="CASCADE",
            name="fk_account_health_account",
        ),
        CheckConstraint(
            "status IN ("
            "'UNKNOWN', "
            "'HEALTHY', "
            "'DEGRADED', "
            "'UNHEALTHY'"
            ")",
            name="ck_account_health_status",
        ),
    )


class AccountEligibilitySnapshotRecord(Base):
    """
    Historical M09 new-entry eligibility decision.
    """

    __tablename__ = "account_eligibility_snapshots"

    snapshot_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    broker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    account_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    available_cash: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    required_cash: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["broker", "account_id"],
            [
                "broker_accounts.broker",
                "broker_accounts.account_id",
            ],
            ondelete="CASCADE",
            name="fk_account_eligibility_account",
        ),
        CheckConstraint(
            "status IN ('ALLOWED', 'BLOCKED')",
            name="ck_account_eligibility_status",
        ),
        CheckConstraint(
            "reason IN ("
            "'ELIGIBLE', "
            "'ACCOUNT_STATUS_UNKNOWN', "
            "'ACCOUNT_INACTIVE', "
            "'ACCOUNT_BLOCKED', "
            "'TRADING_NOT_ENABLED', "
            "'SESSION_NOT_AUTHENTICATED', "
            "'SESSION_EXPIRED', "
            "'SESSION_FAILED', "
            "'BROKER_UNAVAILABLE', "
            "'PROFILE_UNAVAILABLE', "
            "'FUNDS_UNAVAILABLE', "
            "'INSUFFICIENT_FUNDS'"
            ")",
            name="ck_account_eligibility_reason",
        ),
        CheckConstraint(
            "available_cash IS NULL "
            "OR available_cash >= 0",
            name="ck_account_eligibility_cash",
        ),
        CheckConstraint(
            "required_cash IS NULL "
            "OR required_cash >= 0",
            name="ck_account_eligibility_required",
        ),
        CheckConstraint(
            "("
            "status = 'ALLOWED' "
            "AND reason = 'ELIGIBLE'"
            ") OR ("
            "status = 'BLOCKED' "
            "AND reason != 'ELIGIBLE'"
            ")",
            name="ck_account_eligibility_consistency",
        ),
    )

# ============================================================
# M15 Tenant / User / Account membership persistence
# ============================================================


class TenantRecord(Base):
    """
    Durable M15 tenant identity and lifecycle state.

    Authentication credentials, password hashes, tokens, and
    subscription state are deliberately not stored here.
    """

    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(tenant_id)) > 0",
            name="ck_tenants_id_nonempty",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_tenants_name_nonempty",
        ),
    )


class UserRecord(Base):
    """
    Durable M15 user identity, tenant ownership, and role.

    Login credentials and sessions are introduced separately.
    """

    __tablename__ = "users"

    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "tenants.tenant_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(user_id)) > 0",
            name="ck_users_id_nonempty",
        ),
        CheckConstraint(
            "role IN ('ADMIN', 'USER')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "display_name IS NULL "
            "OR length(trim(display_name)) > 0",
            name="ck_users_display_name",
        ),
    )


class UserPasswordCredentialRecord(Base):
    """
    Durable derived password credential for one M15 user.

    Only a versioned password hash is persisted. Plaintext passwords,
    broker credentials, access tokens, and session tokens must never
    be stored in this table.
    """

    __tablename__ = "user_password_credentials"

    tenant_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    password_hash: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            [
                "users.tenant_id",
                "users.user_id",
            ],
            ondelete="CASCADE",
            name=(
                "fk_user_password_credentials_user"
            ),
        ),
        CheckConstraint(
            "length(trim(password_hash)) > 0",
            name=(
                "ck_user_password_credentials_hash"
            ),
        ),
    )


class UserBrokerAccountMembershipRecord(Base):
    """
    Durable ownership of one M09 broker account by one M15 user.

    The global account uniqueness constraint prevents accidental
    cross-user or cross-tenant assignment of the same broker
    account.
    """

    __tablename__ = (
        "user_broker_account_memberships"
    )

    tenant_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    broker: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
    )

    account_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            [
                "users.tenant_id",
                "users.user_id",
            ],
            ondelete="CASCADE",
            name=(
                "fk_user_broker_account_"
                "memberships_user"
            ),
        ),
        ForeignKeyConstraint(
            ["broker", "account_id"],
            [
                "broker_accounts.broker",
                "broker_accounts.account_id",
            ],
            ondelete="CASCADE",
            name=(
                "fk_user_broker_account_"
                "memberships_account"
            ),
        ),
        UniqueConstraint(
            "broker",
            "account_id",
            name=(
                "uq_user_broker_account_"
                "memberships_account"
            ),
        ),
        CheckConstraint(
            "broker IN ('DHAN')",
            name=(
                "ck_user_broker_account_"
                "memberships_broker"
            ),
        ),
    )
