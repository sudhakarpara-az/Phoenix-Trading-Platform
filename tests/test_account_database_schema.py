"""
Phoenix M09-T08 Account Persistence Schema tests.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.schema import (
    AccountEligibilitySnapshotRecord,
    AccountFundSnapshotRecord,
    AccountHealthSnapshotRecord,
    BrokerAccountRecord,
    BrokerConnectivitySnapshotRecord,
    BrokerSessionRecord,
    create_schema,
)


NOW = datetime(
    2026,
    8,
    8,
    10,
    30,
)


def make_database():
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    create_schema(
        engine
    )

    return database, engine


def add_account(
    session: Session,
    *,
    account_id: str = "DHAN-001",
):
    account = BrokerAccountRecord(
        broker="DHAN",
        account_id=account_id,
        account_status="ACTIVE",
        client_name="Phoenix Trader",
        trading_enabled=True,
        product_type="OPTIONS",
        profile_fetched_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )

    session.add(
        account
    )

    session.commit()

    return account


# ============================================================
# Tables
# ============================================================


def test_account_schema_tables_exist():
    database, engine = (
        make_database()
    )

    tables = set(
        inspect(
            engine
        ).get_table_names()
    )

    expected = {
        "broker_accounts",
        "broker_sessions",
        "account_fund_snapshots",
        "broker_connectivity_snapshots",
        "account_health_snapshots",
        "account_eligibility_snapshots",
    }

    assert (
        expected
        <= tables
    )

    database.dispose()


# ============================================================
# Broker account
# ============================================================


def test_broker_account_round_trip():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        record = session.get(
            BrokerAccountRecord,
            {
                "broker": "DHAN",
                "account_id": "DHAN-001",
            },
        )

        assert record is not None

        assert (
            record.account_status
            == "ACTIVE"
        )

        assert (
            record.trading_enabled
            is True
        )

        assert (
            record.client_name
            == "Phoenix Trader"
        )

    database.dispose()


def test_duplicate_broker_account_rejected():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            BrokerAccountRecord(
                broker="DHAN",
                account_id="DHAN-001",
                account_status="ACTIVE",
                trading_enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


def test_invalid_account_status_rejected():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        session.add(
            BrokerAccountRecord(
                broker="DHAN",
                account_id="DHAN-001",
                account_status="INVALID",
                trading_enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


# ============================================================
# Session
# ============================================================


def test_broker_session_round_trip():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        record = BrokerSessionRecord(
            session_id="SESSION-001",
            broker="DHAN",
            account_id="DHAN-001",
            status="AUTHENTICATED",
            authenticated_at=NOW,
            expires_at=None,
            failure_message=None,
            updated_at=NOW,
        )

        session.add(
            record
        )

        session.commit()

        stored = session.get(
            BrokerSessionRecord,
            "SESSION-001",
        )

        assert stored is not None

        assert (
            stored.status
            == "AUTHENTICATED"
        )

    database.dispose()


def test_session_requires_account():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        session.add(
            BrokerSessionRecord(
                session_id="SESSION-001",
                broker="DHAN",
                account_id="MISSING",
                status="AUTHENTICATED",
                authenticated_at=NOW,
                updated_at=NOW,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


def test_invalid_session_status_rejected():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            BrokerSessionRecord(
                session_id="SESSION-001",
                broker="DHAN",
                account_id="DHAN-001",
                status="INVALID",
                updated_at=NOW,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


# ============================================================
# Funds
# ============================================================


def test_fund_snapshot_round_trip():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            AccountFundSnapshotRecord(
                snapshot_id="FUNDS-001",
                broker="DHAN",
                account_id="DHAN-001",
                available_cash=Decimal(
                    "100000.00"
                ),
                available_margin=Decimal(
                    "25000.00"
                ),
                utilized_margin=Decimal(
                    "10000.00"
                ),
                collateral=Decimal(
                    "5000.00"
                ),
                opening_balance=Decimal(
                    "110000.00"
                ),
                fetched_at=NOW,
            )
        )

        session.commit()

        stored = session.get(
            AccountFundSnapshotRecord,
            "FUNDS-001",
        )

        assert stored is not None

        assert (
            stored.available_cash
            == Decimal("100000.00")
        )

    database.dispose()


@pytest.mark.parametrize(
    "field",
    [
        "available_cash",
        "available_margin",
        "utilized_margin",
        "collateral",
    ],
)
def test_negative_funds_rejected(
    field,
):
    database, engine = (
        make_database()
    )

    values = {
        "available_cash":
            Decimal("0"),

        "available_margin":
            Decimal("0"),

        "utilized_margin":
            Decimal("0"),

        "collateral":
            Decimal("0"),
    }

    values[field] = Decimal(
        "-1"
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            AccountFundSnapshotRecord(
                snapshot_id="FUNDS-001",
                broker="DHAN",
                account_id="DHAN-001",
                available_cash=(
                    values[
                        "available_cash"
                    ]
                ),
                available_margin=(
                    values[
                        "available_margin"
                    ]
                ),
                utilized_margin=(
                    values[
                        "utilized_margin"
                    ]
                ),
                collateral=(
                    values[
                        "collateral"
                    ]
                ),
                fetched_at=NOW,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


# ============================================================
# Connectivity
# ============================================================


def test_connectivity_snapshot_round_trip():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            BrokerConnectivitySnapshotRecord(
                snapshot_id="CONN-001",
                broker="DHAN",
                account_id="DHAN-001",
                connected=True,
                checked_at=NOW,
                latency_ms=12.5,
            )
        )

        session.commit()

        stored = session.get(
            BrokerConnectivitySnapshotRecord,
            "CONN-001",
        )

        assert stored is not None

        assert stored.connected is True

        assert (
            stored.latency_ms
            == 12.5
        )

    database.dispose()


def test_negative_connectivity_latency_rejected():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            BrokerConnectivitySnapshotRecord(
                snapshot_id="CONN-001",
                broker="DHAN",
                account_id="DHAN-001",
                connected=False,
                checked_at=NOW,
                latency_ms=-1,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


# ============================================================
# Health
# ============================================================


def test_health_snapshot_round_trip():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            AccountHealthSnapshotRecord(
                snapshot_id="HEALTH-001",
                broker="DHAN",
                account_id="DHAN-001",
                status="HEALTHY",
                checked_at=NOW,
                broker_connected=True,
                session_authenticated=True,
                profile_available=True,
                funds_available=True,
            )
        )

        session.commit()

        stored = session.get(
            AccountHealthSnapshotRecord,
            "HEALTH-001",
        )

        assert stored is not None

        assert (
            stored.status
            == "HEALTHY"
        )

    database.dispose()


def test_invalid_health_status_rejected():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            AccountHealthSnapshotRecord(
                snapshot_id="HEALTH-001",
                broker="DHAN",
                account_id="DHAN-001",
                status="INVALID",
                checked_at=NOW,
                broker_connected=True,
                session_authenticated=True,
                profile_available=True,
                funds_available=True,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


# ============================================================
# Eligibility
# ============================================================


def test_allowed_eligibility_round_trip():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            AccountEligibilitySnapshotRecord(
                snapshot_id="ELIG-001",
                broker="DHAN",
                account_id="DHAN-001",
                status="ALLOWED",
                reason="ELIGIBLE",
                evaluated_at=NOW,
                available_cash=Decimal(
                    "100000"
                ),
                required_cash=Decimal(
                    "6500"
                ),
            )
        )

        session.commit()

        stored = session.get(
            AccountEligibilitySnapshotRecord,
            "ELIG-001",
        )

        assert stored is not None

        assert (
            stored.status
            == "ALLOWED"
        )

        assert (
            stored.reason
            == "ELIGIBLE"
        )

    database.dispose()


def test_blocked_eligibility_round_trip():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            AccountEligibilitySnapshotRecord(
                snapshot_id="ELIG-001",
                broker="DHAN",
                account_id="DHAN-001",
                status="BLOCKED",
                reason="INSUFFICIENT_FUNDS",
                evaluated_at=NOW,
                message=(
                    "insufficient available cash"
                ),
                available_cash=Decimal(
                    "5000"
                ),
                required_cash=Decimal(
                    "6500"
                ),
            )
        )

        session.commit()

        stored = session.get(
            AccountEligibilitySnapshotRecord,
            "ELIG-001",
        )

        assert stored is not None

        assert (
            stored.status
            == "BLOCKED"
        )

    database.dispose()


def test_allowed_with_blocking_reason_rejected():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            AccountEligibilitySnapshotRecord(
                snapshot_id="ELIG-001",
                broker="DHAN",
                account_id="DHAN-001",
                status="ALLOWED",
                reason="ACCOUNT_BLOCKED",
                evaluated_at=NOW,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


def test_blocked_with_eligible_reason_rejected():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        add_account(
            session
        )

        session.add(
            AccountEligibilitySnapshotRecord(
                snapshot_id="ELIG-001",
                broker="DHAN",
                account_id="DHAN-001",
                status="BLOCKED",
                reason="ELIGIBLE",
                evaluated_at=NOW,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()


# ============================================================
# Foreign-key isolation
# ============================================================


def test_fund_snapshot_requires_existing_account():
    database, engine = (
        make_database()
    )

    with Session(engine) as session:
        session.add(
            AccountFundSnapshotRecord(
                snapshot_id="FUNDS-001",
                broker="DHAN",
                account_id="MISSING",
                available_cash=Decimal(
                    "1000"
                ),
                available_margin=Decimal(
                    "0"
                ),
                utilized_margin=Decimal(
                    "0"
                ),
                collateral=Decimal(
                    "0"
                ),
                fetched_at=NOW,
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            session.commit()

        session.rollback()

    database.dispose()