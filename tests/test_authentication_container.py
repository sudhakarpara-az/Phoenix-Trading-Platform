"""
M15-T05 authentication composition tests.
"""

from __future__ import annotations

from datetime import datetime

from src.api.application_session import (
    SessionId,
    SessionToken,
)
from src.api.authentication import (
    Pbkdf2PasswordHasher,
)
from src.app.container import (
    build_authentication_foundation,
    build_persistence_foundation,
)
from src.database.engine import (
    DatabaseConfig,
)


NOW = datetime(
    2026,
    8,
    30,
    19,
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
            "SESSION-CONTAINER"
        )

    def new_token(
        self,
    ) -> SessionToken:
        return SessionToken(
            "phx_container_secret"
        )


def test_authentication_container_reuses_exact_persistence(
) -> None:
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )
    hasher = Pbkdf2PasswordHasher(
        iterations=100_000
    )

    try:
        authentication = (
            build_authentication_foundation(
                persistence=persistence,
                clock=_Clock(),
                password_hasher=hasher,
                token_generator=(
                    _TokenGenerator()
                ),
            )
        )

        assert (
            authentication.persistence
            is persistence
        )
        assert (
            authentication.password_hasher
            is hasher
        )
        assert (
            authentication
            .identity_reader
            ._tenants
            is persistence.tenant_repository
        )
        assert (
            authentication
            .identity_reader
            ._users
            is persistence.user_repository
        )
        assert (
            authentication
            .identity_reader
            ._memberships
            is persistence
            .user_broker_account_membership_repository
        )
        assert (
            authentication
            .credential_reader
            ._credentials
            is persistence
            .user_password_credential_repository
        )
        assert (
            authentication
            .session_store
            ._sessions
            is persistence
            .application_session_repository
        )
        assert (
            persistence
            .application_session_repository
            .list_for_user(
                tenant_id="TENANT-A",
                user_id="USER-001",
            )
            == ()
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
