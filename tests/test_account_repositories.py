"""
Phoenix M09-T09 Account Repository tests.
"""

from datetime import (
    datetime,
    timedelta,
)
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyAccountEligibilitySnapshotRepository,
    SQLAlchemyAccountFundSnapshotRepository,
    SQLAlchemyAccountHealthSnapshotRepository,
    SQLAlchemyBrokerAccountRepository,
    SQLAlchemyBrokerConnectivitySnapshotRepository,
    SQLAlchemyBrokerSessionRepository,
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
from src.database.session import (
    DatabaseSessionManager,
)


NOW = datetime(
    2026,
    8,
    8,
    11,
    0,
)

LATER = (
    NOW
    + timedelta(minutes=5)
)


def make_repositories():
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    create_schema(
        engine
    )

    sessions = DatabaseSessionManager(
        database_engine=database
    )

    sessions.start()

    return {
        "database": database,
        "sessions": sessions,
        "accounts":
            SQLAlchemyBrokerAccountRepository(
                sessions=sessions
            ),
        "sessions_repo":
            SQLAlchemyBrokerSessionRepository(
                sessions=sessions
            ),
        "funds":
            SQLAlchemyAccountFundSnapshotRepository(
                sessions=sessions
            ),
        "connectivity":
            SQLAlchemyBrokerConnectivitySnapshotRepository(
                sessions=sessions
            ),
        "health":
            SQLAlchemyAccountHealthSnapshotRepository(
                sessions=sessions
            ),
        "eligibility":
            SQLAlchemyAccountEligibilitySnapshotRepository(
                sessions=sessions
            ),
    }


def close_repositories(
    repos,
):
    repos[
        "sessions"
    ].stop()

    repos[
        "database"
    ].dispose()


def account_record(
    *,
    account_id="DHAN-001",
    status="ACTIVE",
):
    return BrokerAccountRecord(
        broker="DHAN",
        account_id=account_id,
        account_status=status,
        client_name="Phoenix Trader",
        trading_enabled=True,
        product_type="OPTIONS",
        profile_fetched_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def seed_account(
    repos,
):
    return repos[
        "accounts"
    ].add(
        account_record()
    )


# ============================================================
# Broker account
# ============================================================


def test_add_and_get_broker_account():
    repos = make_repositories()

    seed_account(
        repos
    )

    stored = repos[
        "accounts"
    ].get(
        broker="DHAN",
        account_id="DHAN-001",
    )

    assert stored is not None

    assert (
        stored.account_status
        == "ACTIVE"
    )

    close_repositories(
        repos
    )


def test_require_broker_account():
    repos = make_repositories()

    seed_account(
        repos
    )

    stored = repos[
        "accounts"
    ].require(
        broker="DHAN",
        account_id="DHAN-001",
    )

    assert (
        stored.account_id
        == "DHAN-001"
    )

    close_repositories(
        repos
    )


def test_require_missing_account_raises():
    repos = make_repositories()

    with pytest.raises(
        KeyError
    ):
        repos[
            "accounts"
        ].require(
            broker="DHAN",
            account_id="MISSING",
        )

    close_repositories(
        repos
    )


def test_update_broker_account():
    repos = make_repositories()

    seed_account(
        repos
    )

    record = repos[
        "accounts"
    ].require(
        broker="DHAN",
        account_id="DHAN-001",
    )

    record.account_status = "INACTIVE"
    record.trading_enabled = False
    record.updated_at = LATER

    updated = repos[
        "accounts"
    ].update(
        record
    )

    assert (
        updated.account_status
        == "INACTIVE"
    )

    stored = repos[
        "accounts"
    ].require(
        broker="DHAN",
        account_id="DHAN-001",
    )

    assert (
        stored.account_status
        == "INACTIVE"
    )

    close_repositories(
        repos
    )


def test_list_all_accounts():
    repos = make_repositories()

    repos[
        "accounts"
    ].add(
        account_record(
            account_id="DHAN-001"
        )
    )

    repos[
        "accounts"
    ].add(
        account_record(
            account_id="DHAN-002"
        )
    )

    records = repos[
        "accounts"
    ].list_all()

    assert len(records) == 2

    close_repositories(
        repos
    )


# ============================================================
# Broker sessions
# ============================================================


def test_broker_session_repository():
    repos = make_repositories()

    seed_account(
        repos
    )

    repos[
        "sessions_repo"
    ].add(
        BrokerSessionRecord(
            session_id="SESSION-001",
            broker="DHAN",
            account_id="DHAN-001",
            status="AUTHENTICATED",
            authenticated_at=NOW,
            updated_at=NOW,
        )
    )

    stored = repos[
        "sessions_repo"
    ].require(
        "SESSION-001"
    )

    assert (
        stored.status
        == "AUTHENTICATED"
    )

    close_repositories(
        repos
    )


def test_latest_broker_session():
    repos = make_repositories()

    seed_account(
        repos
    )

    repos[
        "sessions_repo"
    ].add(
        BrokerSessionRecord(
            session_id="SESSION-001",
            broker="DHAN",
            account_id="DHAN-001",
            status="AUTHENTICATED",
            authenticated_at=NOW,
            updated_at=NOW,
        )
    )

    repos[
        "sessions_repo"
    ].add(
        BrokerSessionRecord(
            session_id="SESSION-002",
            broker="DHAN",
            account_id="DHAN-001",
            status="EXPIRED",
            authenticated_at=NOW,
            updated_at=LATER,
        )
    )

    latest = repos[
        "sessions_repo"
    ].latest_for_account(
        broker="DHAN",
        account_id="DHAN-001",
    )

    assert latest is not None

    assert (
        latest.session_id
        == "SESSION-002"
    )

    close_repositories(
        repos
    )


# ============================================================
# Funds
# ============================================================


def test_fund_repository():
    repos = make_repositories()

    seed_account(
        repos
    )

    repos[
        "funds"
    ].add(
        AccountFundSnapshotRecord(
            snapshot_id="FUNDS-001",
            broker="DHAN",
            account_id="DHAN-001",
            available_cash=Decimal(
                "100000"
            ),
            available_margin=Decimal(
                "10000"
            ),
            utilized_margin=Decimal(
                "5000"
            ),
            collateral=Decimal(
                "0"
            ),
            fetched_at=NOW,
        )
    )

    stored = repos[
        "funds"
    ].require(
        "FUNDS-001"
    )

    assert (
        stored.available_cash
        == Decimal("100000.00")
    )

    close_repositories(
        repos
    )


def test_latest_fund_snapshot():
    repos = make_repositories()

    seed_account(
        repos
    )

    repos[
        "funds"
    ].add(
        AccountFundSnapshotRecord(
            snapshot_id="FUNDS-001",
            broker="DHAN",
            account_id="DHAN-001",
            available_cash=Decimal(
                "100000"
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

    repos[
        "funds"
    ].add(
        AccountFundSnapshotRecord(
            snapshot_id="FUNDS-002",
            broker="DHAN",
            account_id="DHAN-001",
            available_cash=Decimal(
                "90000"
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
            fetched_at=LATER,
        )
    )

    latest = repos[
        "funds"
    ].latest_for_account(
        broker="DHAN",
        account_id="DHAN-001",
    )

    assert latest is not None

    assert (
        latest.snapshot_id
        == "FUNDS-002"
    )

    close_repositories(
        repos
    )


# ============================================================
# Connectivity
# ============================================================


def test_latest_connectivity_snapshot():
    repos = make_repositories()

    seed_account(
        repos
    )

    repos[
        "connectivity"
    ].add(
        BrokerConnectivitySnapshotRecord(
            snapshot_id="CONN-001",
            broker="DHAN",
            account_id="DHAN-001",
            connected=True,
            checked_at=NOW,
        )
    )

    repos[
        "connectivity"
    ].add(
        BrokerConnectivitySnapshotRecord(
            snapshot_id="CONN-002",
            broker="DHAN",
            account_id="DHAN-001",
            connected=False,
            checked_at=LATER,
            message="disconnected",
        )
    )

    latest = repos[
        "connectivity"
    ].latest_for_account(
        broker="DHAN",
        account_id="DHAN-001",
    )

    assert latest is not None

    assert (
        latest.snapshot_id
        == "CONN-002"
    )

    assert (
        latest.connected
        is False
    )

    close_repositories(
        repos
    )


# ============================================================
# Health
# ============================================================


def test_latest_health_snapshot():
    repos = make_repositories()

    seed_account(
        repos
    )

    repos[
        "health"
    ].add(
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

    latest = repos[
        "health"
    ].latest_for_account(
        broker="DHAN",
        account_id="DHAN-001",
    )

    assert latest is not None

    assert (
        latest.status
        == "HEALTHY"
    )

    close_repositories(
        repos
    )


# ============================================================
# Eligibility
# ============================================================


def test_latest_eligibility_snapshot():
    repos = make_repositories()

    seed_account(
        repos
    )

    repos[
        "eligibility"
    ].add(
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

    repos[
        "eligibility"
    ].add(
        AccountEligibilitySnapshotRecord(
            snapshot_id="ELIG-002",
            broker="DHAN",
            account_id="DHAN-001",
            status="BLOCKED",
            reason="INSUFFICIENT_FUNDS",
            evaluated_at=LATER,
            available_cash=Decimal(
                "5000"
            ),
            required_cash=Decimal(
                "6500"
            ),
        )
    )

    latest = repos[
        "eligibility"
    ].latest_for_account(
        broker="DHAN",
        account_id="DHAN-001",
    )

    assert latest is not None

    assert (
        latest.snapshot_id
        == "ELIG-002"
    )

    assert (
        latest.status
        == "BLOCKED"
    )

    close_repositories(
        repos
    )


# ============================================================
# Foreign-key protection
# ============================================================


def test_snapshot_without_account_rejected():
    repos = make_repositories()

    with pytest.raises(
        IntegrityError
    ):
        repos[
            "funds"
        ].add(
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

    close_repositories(
        repos
    )