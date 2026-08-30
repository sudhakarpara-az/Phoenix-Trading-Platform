"""
M15-T05 durable application-session persistence tests.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
)

import pytest
from sqlalchemy.exc import IntegrityError

from src.api.access_control import (
    AuthenticatedPrincipal,
    TenantId,
    UserId,
    UserRole,
)
from src.api.application_session import (
    ApplicationSession,
    ApplicationSessionService,
    SessionId,
    SessionToken,
    session_token_digest,
)
from src.database.application_session_persistence import (
    RepositoryApplicationSessionStore,
)
from src.database.authentication_persistence import (
    RepositoryAuthenticationIdentityReader,
)
from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyApplicationSessionRepository,
    SQLAlchemyTenantRepository,
    SQLAlchemyUserBrokerAccountMembershipRepository,
    SQLAlchemyUserRepository,
)
from src.database.schema import (
    ApplicationSessionRecord,
    TenantRecord,
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
    18,
    0,
)


class _Clock:
    def now(
        self,
    ) -> datetime:
        return NOW


class _TokenGenerator:
    def new_session_id(
        self,
    ) -> SessionId:
        return SessionId(
            "SESSION-001"
        )

    def new_token(
        self,
    ) -> SessionToken:
        return SessionToken(
            "phx_persistence_secret"
        )


def _make_database(
) -> tuple[
    DatabaseEngine,
    DatabaseSessionManager,
]:
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

    return database, sessions


def _seed_user(
    *,
    tenants: SQLAlchemyTenantRepository,
    users: SQLAlchemyUserRepository,
) -> None:
    tenants.add(
        TenantRecord(
            tenant_id="TENANT-A",
            name="Tenant A",
            enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    users.add(
        UserRecord(
            tenant_id="TENANT-A",
            user_id="USER-001",
            role="USER",
            display_name="Phoenix User",
            enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )
    )


def _record(
    *,
    session_id: str = "SESSION-001",
    token_digest: str = "a" * 64,
    issued_at: datetime = NOW,
    expires_at: datetime | None = None,
) -> ApplicationSessionRecord:
    return ApplicationSessionRecord(
        session_id=session_id,
        tenant_id="TENANT-A",
        user_id="USER-001",
        token_digest=token_digest,
        issued_at=issued_at,
        expires_at=(
            expires_at
            if expires_at is not None
            else issued_at
            + timedelta(hours=8)
        ),
        revoked_at=None,
    )


def test_application_session_repository_round_trip(
) -> None:
    database, sessions = _make_database()
    tenants = SQLAlchemyTenantRepository(
        sessions=sessions
    )
    users = SQLAlchemyUserRepository(
        sessions=sessions
    )
    repository = (
        SQLAlchemyApplicationSessionRepository(
            sessions=sessions
        )
    )

    try:
        _seed_user(
            tenants=tenants,
            users=users,
        )
        repository.add(
            _record()
        )

        stored = repository.require(
            "SESSION-001"
        )
        assert stored.token_digest == "a" * 64
        assert (
            repository.get_by_token_digest(
                "a" * 64
            )
            is not None
        )
        listed = repository.list_for_user(
            tenant_id="TENANT-A",
            user_id="USER-001",
        )
        assert len(listed) == 1
        assert listed[0].session_id == (
            stored.session_id
        )
        assert listed[0].token_digest == (
            stored.token_digest
        )

        stored.revoked_at = NOW + timedelta(
            minutes=5
        )
        updated = repository.update(
            stored
        )
        assert updated.revoked_at == (
            NOW + timedelta(minutes=5)
        )

    finally:
        sessions.stop()
        database.dispose()


def test_application_session_requires_existing_user(
) -> None:
    database, sessions = _make_database()
    repository = (
        SQLAlchemyApplicationSessionRepository(
            sessions=sessions
        )
    )

    try:
        with pytest.raises(
            IntegrityError
        ):
            repository.add(
                _record()
            )

    finally:
        sessions.stop()
        database.dispose()


@pytest.mark.parametrize(
    "record",
    [
        _record(
            session_id="  "
        ),
        _record(
            token_digest="short"
        ),
        _record(
            expires_at=NOW
        ),
    ],
)
def test_application_session_constraints_fail_closed(
    record: ApplicationSessionRecord,
) -> None:
    database, sessions = _make_database()
    tenants = SQLAlchemyTenantRepository(
        sessions=sessions
    )
    users = SQLAlchemyUserRepository(
        sessions=sessions
    )
    repository = (
        SQLAlchemyApplicationSessionRepository(
            sessions=sessions
        )
    )

    try:
        _seed_user(
            tenants=tenants,
            users=users,
        )

        with pytest.raises(
            IntegrityError
        ):
            repository.add(
                record
            )

    finally:
        sessions.stop()
        database.dispose()


def test_token_digest_is_globally_unique(
) -> None:
    database, sessions = _make_database()
    tenants = SQLAlchemyTenantRepository(
        sessions=sessions
    )
    users = SQLAlchemyUserRepository(
        sessions=sessions
    )
    repository = (
        SQLAlchemyApplicationSessionRepository(
            sessions=sessions
        )
    )

    try:
        _seed_user(
            tenants=tenants,
            users=users,
        )
        repository.add(
            _record()
        )

        with pytest.raises(
            IntegrityError
        ):
            repository.add(
                _record(
                    session_id="SESSION-002"
                )
            )

    finally:
        sessions.stop()
        database.dispose()


def test_session_survives_service_recomposition_without_raw_token(
) -> None:
    database, sessions = _make_database()
    tenants = SQLAlchemyTenantRepository(
        sessions=sessions
    )
    users = SQLAlchemyUserRepository(
        sessions=sessions
    )
    memberships = (
        SQLAlchemyUserBrokerAccountMembershipRepository(
            sessions=sessions
        )
    )
    repository = (
        SQLAlchemyApplicationSessionRepository(
            sessions=sessions
        )
    )

    try:
        _seed_user(
            tenants=tenants,
            users=users,
        )
        identities = (
            RepositoryAuthenticationIdentityReader(
                tenants=tenants,
                users=users,
                memberships=memberships,
            )
        )
        first_store = (
            RepositoryApplicationSessionStore(
                sessions=repository
            )
        )
        first_service = ApplicationSessionService(
            store=first_store,
            identities=identities,
            clock=_Clock(),
            token_generator=(
                _TokenGenerator()
            ),
        )
        issued = first_service.issue(
            AuthenticatedPrincipal(
                tenant_id=TenantId(
                    "TENANT-A"
                ),
                user_id=UserId(
                    "USER-001"
                ),
                role=UserRole.USER,
            )
        )

        records = repository.list_for_user(
            tenant_id="TENANT-A",
            user_id="USER-001",
        )
        assert len(records) == 1
        assert records[0].token_digest == (
            session_token_digest(
                issued.token
            )
        )
        assert issued.token.value not in repr(
            records[0]
        )

        recomposed_service = (
            ApplicationSessionService(
                store=(
                    RepositoryApplicationSessionStore(
                        sessions=repository
                    )
                ),
                identities=identities,
                clock=_Clock(),
            )
        )
        principal = (
            recomposed_service.authenticate(
                issued.token
            )
        )

        assert principal.user_id == UserId(
            "USER-001"
        )

    finally:
        sessions.stop()
        database.dispose()
