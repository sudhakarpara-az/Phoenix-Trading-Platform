"""
M15 durable application-session adapter.

Only opaque-token SHA-256 digests are mapped to persistence. Raw
application bearer tokens never enter this module or its repository.
"""

from __future__ import annotations

from src.api.access_control import (
    TenantId,
    UserId,
)
from src.api.application_session import (
    ApplicationSession,
    SessionId,
)
from src.database.repositories.interfaces import (
    ApplicationSessionRepository,
)
from src.database.schema import (
    ApplicationSessionRecord,
)


class RepositoryApplicationSessionStore:
    __slots__ = (
        "_sessions",
    )

    def __init__(
        self,
        *,
        sessions: ApplicationSessionRepository,
    ) -> None:
        if sessions is None:
            raise TypeError(
                "sessions cannot be None"
            )

        self._sessions = sessions

    @staticmethod
    def _to_record(
        session: ApplicationSession,
    ) -> ApplicationSessionRecord:
        if not isinstance(
            session,
            ApplicationSession,
        ):
            raise TypeError(
                "session must be ApplicationSession"
            )

        return ApplicationSessionRecord(
            session_id=(
                session.session_id.value
            ),
            tenant_id=session.tenant_id.value,
            user_id=session.user_id.value,
            token_digest=session.token_digest,
            issued_at=session.issued_at,
            expires_at=session.expires_at,
            revoked_at=session.revoked_at,
        )

    @staticmethod
    def _to_domain(
        record: ApplicationSessionRecord,
    ) -> ApplicationSession:
        return ApplicationSession(
            session_id=SessionId(
                record.session_id
            ),
            tenant_id=TenantId(
                record.tenant_id
            ),
            user_id=UserId(
                record.user_id
            ),
            token_digest=record.token_digest,
            issued_at=record.issued_at,
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
        )

    def add(
        self,
        session: ApplicationSession,
    ) -> ApplicationSession:
        record = self._sessions.add(
            self._to_record(
                session
            )
        )

        return self._to_domain(
            record
        )

    def get_by_token_digest(
        self,
        token_digest: str,
    ) -> ApplicationSession | None:
        record = (
            self._sessions
            .get_by_token_digest(
                token_digest
            )
        )

        if record is None:
            return None

        return self._to_domain(
            record
        )

    def update(
        self,
        session: ApplicationSession,
    ) -> ApplicationSession:
        record = self._sessions.update(
            self._to_record(
                session
            )
        )

        return self._to_domain(
            record
        )


__all__ = [
    "RepositoryApplicationSessionStore",
]
