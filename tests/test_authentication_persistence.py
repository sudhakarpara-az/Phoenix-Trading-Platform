"""
M15-T04 durable credential and authentication-adapter tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.account.account_types import (
    BrokerAccountId,
)
from src.api.access_control import (
    TenantId,
    UserId,
    UserRole,
)
from src.api.authentication import (
    AuthenticationError,
    AuthenticationService,
    LoginRequest,
    Pbkdf2PasswordHasher,
)
from src.database.authentication_persistence import (
    RepositoryAuthenticationIdentityReader,
    RepositoryPasswordCredentialReader,
)
from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyBrokerAccountRepository,
    SQLAlchemyTenantRepository,
    SQLAlchemyUserBrokerAccountMembershipRepository,
    SQLAlchemyUserPasswordCredentialRepository,
    SQLAlchemyUserRepository,
)
from src.database.schema import (
    BrokerAccountRecord,
    TenantRecord,
    UserBrokerAccountMembershipRecord,
    UserPasswordCredentialRecord,
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
    16,
    0,
)

PASSWORD = "correct horse battery staple"


@dataclass(
    frozen=True,
    slots=True,
)
class _Repositories:
    database: DatabaseEngine
    sessions: DatabaseSessionManager
    tenants: SQLAlchemyTenantRepository
    users: SQLAlchemyUserRepository
    credentials: SQLAlchemyUserPasswordCredentialRepository
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
        credentials=(
            SQLAlchemyUserPasswordCredentialRepository(
                sessions=sessions
            )
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


def _seed_identity(
    repositories: _Repositories,
    *,
    tenant_enabled: bool = True,
    user_enabled: bool = True,
) -> None:
    repositories.tenants.add(
        TenantRecord(
            tenant_id="TENANT-A",
            name="Tenant A",
            enabled=tenant_enabled,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repositories.users.add(
        UserRecord(
            tenant_id="TENANT-A",
            user_id="USER-001",
            role="USER",
            display_name="Phoenix User",
            enabled=user_enabled,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repositories.broker_accounts.add(
        BrokerAccountRecord(
            broker="DHAN",
            account_id="DHAN-001",
            account_status="ACTIVE",
            client_name="Phoenix Trader",
            trading_enabled=True,
            product_type="OPTIONS",
            profile_fetched_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repositories.memberships.add(
        UserBrokerAccountMembershipRecord(
            tenant_id="TENANT-A",
            user_id="USER-001",
            broker="DHAN",
            account_id="DHAN-001",
            created_at=NOW,
        )
    )


def _credential_record(
    password_hash: str,
) -> UserPasswordCredentialRecord:
    return UserPasswordCredentialRecord(
        tenant_id="TENANT-A",
        user_id="USER-001",
        password_hash=password_hash,
        created_at=NOW,
        updated_at=NOW,
    )


def test_credential_repository_round_trip_and_update(
) -> None:
    repositories = _make_repositories()

    try:
        _seed_identity(
            repositories
        )
        original_hash = "derived-password-hash-v1"
        stored = repositories.credentials.add(
            _credential_record(
                original_hash
            )
        )

        assert stored.password_hash == original_hash
        loaded = repositories.credentials.require(
            tenant_id="TENANT-A",
            user_id="USER-001",
        )
        assert loaded.password_hash == original_hash

        loaded.password_hash = (
            "derived-password-hash-v2"
        )
        loaded.updated_at = datetime(
            2026,
            8,
            30,
            16,
            30,
        )
        updated = repositories.credentials.update(
            loaded
        )

        assert updated.password_hash == (
            "derived-password-hash-v2"
        )

    finally:
        repositories.close()


def test_credential_requires_existing_user(
) -> None:
    repositories = _make_repositories()

    try:
        with pytest.raises(
            IntegrityError
        ):
            repositories.credentials.add(
                _credential_record(
                    "derived-password-hash"
                )
            )

    finally:
        repositories.close()


def test_empty_password_hash_is_rejected(
) -> None:
    repositories = _make_repositories()

    try:
        _seed_identity(
            repositories
        )

        with pytest.raises(
            IntegrityError
        ):
            repositories.credentials.add(
                _credential_record("  ")
            )

    finally:
        repositories.close()


def test_identity_reader_maps_lifecycle_role_and_accounts(
) -> None:
    repositories = _make_repositories()

    try:
        _seed_identity(
            repositories,
            tenant_enabled=False,
            user_enabled=True,
        )
        reader = (
            RepositoryAuthenticationIdentityReader(
                tenants=repositories.tenants,
                users=repositories.users,
                memberships=(
                    repositories.memberships
                ),
            )
        )

        identity = (
            reader.get_authentication_identity(
                tenant_id=TenantId("TENANT-A"),
                user_id=UserId("USER-001"),
            )
        )

        assert identity is not None
        assert identity.role is UserRole.USER
        assert identity.tenant_enabled is False
        assert identity.user_enabled is True
        assert identity.account_ids == (
            BrokerAccountId("DHAN-001"),
        )

    finally:
        repositories.close()


def test_identity_reader_returns_none_for_missing_identity(
) -> None:
    repositories = _make_repositories()

    try:
        reader = (
            RepositoryAuthenticationIdentityReader(
                tenants=repositories.tenants,
                users=repositories.users,
                memberships=(
                    repositories.memberships
                ),
            )
        )

        assert (
            reader.get_authentication_identity(
                tenant_id=TenantId("TENANT-A"),
                user_id=UserId("USER-001"),
            )
            is None
        )

    finally:
        repositories.close()


def test_credential_reader_maps_hash_without_exposing_repr(
) -> None:
    repositories = _make_repositories()

    try:
        _seed_identity(
            repositories
        )
        stored_hash = "derived-password-hash"
        repositories.credentials.add(
            _credential_record(
                stored_hash
            )
        )
        reader = RepositoryPasswordCredentialReader(
            credentials=repositories.credentials
        )

        credential = reader.get_password_credential(
            tenant_id=TenantId("TENANT-A"),
            user_id=UserId("USER-001"),
        )

        assert credential is not None
        assert credential.password_hash == stored_hash
        assert stored_hash not in repr(
            credential
        )

    finally:
        repositories.close()


def test_durable_readers_authenticate_end_to_end(
) -> None:
    repositories = _make_repositories()

    try:
        _seed_identity(
            repositories
        )
        hasher = Pbkdf2PasswordHasher(
            iterations=100_000
        )
        repositories.credentials.add(
            _credential_record(
                hasher.hash_password(
                    PASSWORD
                )
            )
        )
        identities = (
            RepositoryAuthenticationIdentityReader(
                tenants=repositories.tenants,
                users=repositories.users,
                memberships=(
                    repositories.memberships
                ),
            )
        )
        credentials = (
            RepositoryPasswordCredentialReader(
                credentials=(
                    repositories.credentials
                )
            )
        )
        service = AuthenticationService(
            identities=identities,
            credentials=credentials,
            password_hasher=hasher,
        )

        principal = service.authenticate(
            LoginRequest(
                tenant_id=TenantId("TENANT-A"),
                user_id=UserId("USER-001"),
                password=PASSWORD,
            )
        )

        assert principal.tenant_id == TenantId(
            "TENANT-A"
        )
        assert principal.user_id == UserId(
            "USER-001"
        )
        assert principal.account_ids == (
            BrokerAccountId("DHAN-001"),
        )

        with pytest.raises(
            AuthenticationError,
            match="^authentication failed$",
        ):
            service.authenticate(
                LoginRequest(
                    tenant_id=TenantId(
                        "TENANT-A"
                    ),
                    user_id=UserId(
                        "USER-001"
                    ),
                    password="wrong password",
                )
            )

    finally:
        repositories.close()
