"""
M15-T02 tenant, user, role, and account-membership persistence tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.app.container import (
    build_persistence_foundation,
)
from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyBrokerAccountRepository,
    SQLAlchemyTenantRepository,
    SQLAlchemyUserBrokerAccountMembershipRepository,
    SQLAlchemyUserRepository,
)
from src.database.schema import (
    BrokerAccountRecord,
    TenantRecord,
    UserBrokerAccountMembershipRecord,
    UserRecord,
    create_schema,
)
from src.database.session import (
    DatabaseSessionManager,
)


NOW = datetime(
    2026,
    8,
    30,
    12,
    0,
)


@dataclass(
    frozen=True,
    slots=True,
)
class _Repositories:
    database: DatabaseEngine
    sessions: DatabaseSessionManager
    tenants: SQLAlchemyTenantRepository
    users: SQLAlchemyUserRepository
    memberships: (
        SQLAlchemyUserBrokerAccountMembershipRepository
    )
    broker_accounts: SQLAlchemyBrokerAccountRepository

    def close(
        self,
    ) -> None:
        self.sessions.stop()
        self.database.dispose()


def _make_repositories(
) -> _Repositories:
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

    return _Repositories(
        database=database,
        sessions=sessions,
        tenants=SQLAlchemyTenantRepository(
            sessions=sessions
        ),
        users=SQLAlchemyUserRepository(
            sessions=sessions
        ),
        memberships=(
            SQLAlchemyUserBrokerAccountMembershipRepository(
                sessions=sessions
            )
        ),
        broker_accounts=(
            SQLAlchemyBrokerAccountRepository(
                sessions=sessions
            )
        ),
    )


def _tenant_record(
    *,
    tenant_id: str = "TENANT-A",
    name: str = "Tenant A",
) -> TenantRecord:
    return TenantRecord(
        tenant_id=tenant_id,
        name=name,
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _user_record(
    *,
    tenant_id: str = "TENANT-A",
    user_id: str = "USER-001",
    role: str = "USER",
) -> UserRecord:
    return UserRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        display_name="Phoenix User",
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _broker_account_record(
    *,
    account_id: str = "DHAN-001",
) -> BrokerAccountRecord:
    return BrokerAccountRecord(
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


def _membership_record(
    *,
    tenant_id: str = "TENANT-A",
    user_id: str = "USER-001",
    account_id: str = "DHAN-001",
) -> UserBrokerAccountMembershipRecord:
    return UserBrokerAccountMembershipRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        broker="DHAN",
        account_id=account_id,
        created_at=NOW,
    )


def _seed_user_and_account(
    repositories: _Repositories,
    *,
    tenant_id: str = "TENANT-A",
    user_id: str = "USER-001",
    account_id: str = "DHAN-001",
) -> None:
    repositories.tenants.add(
        _tenant_record(
            tenant_id=tenant_id,
            name=f"Tenant {tenant_id}",
        )
    )
    repositories.users.add(
        _user_record(
            tenant_id=tenant_id,
            user_id=user_id,
        )
    )
    repositories.broker_accounts.add(
        _broker_account_record(
            account_id=account_id
        )
    )


def test_tenant_repository_round_trip_and_update(
) -> None:
    repositories = _make_repositories()

    try:
        repositories.tenants.add(
            _tenant_record()
        )

        stored = repositories.tenants.require(
            "TENANT-A"
        )

        assert stored.name == "Tenant A"
        assert stored.enabled is True
        listed = repositories.tenants.list_all()

        assert len(listed) == 1
        assert listed[0].tenant_id == "TENANT-A"

        stored.enabled = False

        updated = repositories.tenants.update(
            stored
        )

        assert updated.enabled is False
        assert (
            repositories.tenants
            .require("TENANT-A")
            .enabled
            is False
        )

    finally:
        repositories.close()


def test_user_repository_is_tenant_scoped(
) -> None:
    repositories = _make_repositories()

    try:
        repositories.tenants.add(
            _tenant_record(
                tenant_id="TENANT-A",
                name="Tenant A",
            )
        )
        repositories.tenants.add(
            _tenant_record(
                tenant_id="TENANT-B",
                name="Tenant B",
            )
        )

        repositories.users.add(
            _user_record(
                tenant_id="TENANT-A",
                user_id="SHARED-USER",
                role="ADMIN",
            )
        )
        repositories.users.add(
            _user_record(
                tenant_id="TENANT-B",
                user_id="SHARED-USER",
                role="USER",
            )
        )

        tenant_a = (
            repositories.users
            .require(
                tenant_id="TENANT-A",
                user_id="SHARED-USER",
            )
        )
        tenant_b = (
            repositories.users
            .require(
                tenant_id="TENANT-B",
                user_id="SHARED-USER",
            )
        )

        assert tenant_a.role == "ADMIN"
        assert tenant_b.role == "USER"
        listed = (
            repositories.users
            .list_for_tenant("TENANT-A")
        )

        assert len(listed) == 1
        assert listed[0].tenant_id == "TENANT-A"
        assert listed[0].user_id == "SHARED-USER"

    finally:
        repositories.close()


def test_user_requires_existing_tenant(
) -> None:
    repositories = _make_repositories()

    try:
        with pytest.raises(
            IntegrityError
        ):
            repositories.users.add(
                _user_record()
            )

    finally:
        repositories.close()


def test_invalid_user_role_is_rejected(
) -> None:
    repositories = _make_repositories()

    try:
        repositories.tenants.add(
            _tenant_record()
        )

        with pytest.raises(
            IntegrityError
        ):
            repositories.users.add(
                _user_record(
                    role="SUPERUSER"
                )
            )

    finally:
        repositories.close()


def test_membership_requires_existing_user(
) -> None:
    repositories = _make_repositories()

    try:
        repositories.tenants.add(
            _tenant_record()
        )
        repositories.broker_accounts.add(
            _broker_account_record()
        )

        with pytest.raises(
            IntegrityError
        ):
            repositories.memberships.add(
                _membership_record()
            )

    finally:
        repositories.close()


def test_membership_requires_existing_broker_account(
) -> None:
    repositories = _make_repositories()

    try:
        repositories.tenants.add(
            _tenant_record()
        )
        repositories.users.add(
            _user_record()
        )

        with pytest.raises(
            IntegrityError
        ):
            repositories.memberships.add(
                _membership_record()
            )

    finally:
        repositories.close()


def test_membership_round_trip_and_account_lookup(
) -> None:
    repositories = _make_repositories()

    try:
        _seed_user_and_account(
            repositories
        )

        membership = (
            repositories.memberships.add(
                _membership_record()
            )
        )

        assert (
            repositories.memberships.get(
                tenant_id="TENANT-A",
                user_id="USER-001",
                broker="DHAN",
                account_id="DHAN-001",
            )
            is not None
        )
        listed = (
            repositories.memberships
            .list_for_user(
                tenant_id="TENANT-A",
                user_id="USER-001",
            )
        )

        assert len(listed) == 1
        assert listed[0].tenant_id == membership.tenant_id
        assert listed[0].user_id == membership.user_id
        assert listed[0].account_id == membership.account_id

        owner = (
            repositories.memberships
            .get_for_account(
                broker="DHAN",
                account_id="DHAN-001",
            )
        )

        assert owner is not None
        assert owner.tenant_id == "TENANT-A"
        assert owner.user_id == "USER-001"

    finally:
        repositories.close()


def test_broker_account_cannot_cross_memberships(
) -> None:
    repositories = _make_repositories()

    try:
        repositories.tenants.add(
            _tenant_record(
                tenant_id="TENANT-A",
                name="Tenant A",
            )
        )
        repositories.tenants.add(
            _tenant_record(
                tenant_id="TENANT-B",
                name="Tenant B",
            )
        )
        repositories.users.add(
            _user_record(
                tenant_id="TENANT-A",
                user_id="USER-A",
            )
        )
        repositories.users.add(
            _user_record(
                tenant_id="TENANT-B",
                user_id="USER-B",
            )
        )
        repositories.broker_accounts.add(
            _broker_account_record()
        )

        repositories.memberships.add(
            _membership_record(
                tenant_id="TENANT-A",
                user_id="USER-A",
            )
        )

        with pytest.raises(
            IntegrityError
        ):
            repositories.memberships.add(
                _membership_record(
                    tenant_id="TENANT-B",
                    user_id="USER-B",
                )
            )

    finally:
        repositories.close()


def test_membership_remove_is_idempotent(
) -> None:
    repositories = _make_repositories()

    try:
        _seed_user_and_account(
            repositories
        )
        repositories.memberships.add(
            _membership_record()
        )

        assert (
            repositories.memberships.remove(
                tenant_id="TENANT-A",
                user_id="USER-001",
                broker="DHAN",
                account_id="DHAN-001",
            )
            is True
        )
        assert (
            repositories.memberships.remove(
                tenant_id="TENANT-A",
                user_id="USER-001",
                broker="DHAN",
                account_id="DHAN-001",
            )
            is False
        )

    finally:
        repositories.close()


def test_persistence_container_reuses_shared_sessions(
) -> None:
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    try:
        repositories = (
            persistence.tenant_repository,
            persistence.user_repository,
            (
                persistence
                .user_password_credential_repository
            ),
            (
                persistence
                .user_broker_account_membership_repository
            ),
        )

        for repository in repositories:
            assert (
                repository._sessions
                is persistence.sessions
            )

        assert (
            persistence.tenant_repository
            .list_all()
            == ()
        )
        assert (
            persistence.user_repository
            .list_for_tenant("TENANT-A")
            == ()
        )
        assert (
            persistence
            .user_password_credential_repository
            .get(
                tenant_id="TENANT-A",
                user_id="USER-001",
            )
            is None
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
