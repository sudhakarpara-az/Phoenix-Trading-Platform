"""
Phoenix M15 application login and session lifecycle foundation.

Application bearer tokens are opaque high-entropy values. Only their
SHA-256 digests cross the persistence boundary; raw tokens are returned
once to the successful login caller and are never stored.

This module is transport-neutral. It does not expose HTTP routes,
cookies, headers, dashboards, or trading operations.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
    replace,
)
from datetime import (
    datetime,
    timedelta,
)
from hashlib import sha256
from secrets import token_urlsafe
from string import hexdigits
from typing import Protocol

from src.api.access_control import (
    AuthenticatedPrincipal,
    TenantId,
    UserId,
)
from src.api.authentication import (
    AuthenticationIdentityReader,
    LoginRequest,
)


_SESSION_TOKEN_BYTES = 32
_SESSION_ID_BYTES = 18
_TOKEN_DIGEST_LENGTH = 64
_DEFAULT_SESSION_LIFETIME = timedelta(
    hours=8
)
_MAXIMUM_SESSION_LIFETIME = timedelta(
    days=30
)


@dataclass(
    frozen=True,
    slots=True,
)
class SessionId:
    value: str

    def __post_init__(
        self,
    ) -> None:
        if type(self.value) is not str:
            raise TypeError(
                "session id must be str"
            )

        if not self.value:
            raise ValueError(
                "session id cannot be empty"
            )

        if self.value.strip() != self.value:
            raise ValueError(
                "session id cannot contain outer whitespace"
            )

    def __str__(
        self,
    ) -> str:
        return self.value


@dataclass(
    frozen=True,
    slots=True,
)
class SessionToken:
    value: str = field(
        repr=False
    )

    def __post_init__(
        self,
    ) -> None:
        if type(self.value) is not str:
            raise TypeError(
                "session token must be str"
            )

        if not self.value:
            raise ValueError(
                "session token cannot be empty"
            )

        if self.value.strip() != self.value:
            raise ValueError(
                "session token cannot contain outer whitespace"
            )


def session_token_digest(
    token: SessionToken,
) -> str:
    if not isinstance(
        token,
        SessionToken,
    ):
        raise TypeError(
            "token must be SessionToken"
        )

    return sha256(
        token.value.encode("utf-8")
    ).hexdigest()


@dataclass(
    frozen=True,
    slots=True,
)
class ApplicationSession:
    session_id: SessionId
    tenant_id: TenantId
    user_id: UserId
    token_digest: str = field(
        repr=False
    )
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.session_id,
            SessionId,
        ):
            raise TypeError(
                "session_id must be SessionId"
            )

        if not isinstance(
            self.tenant_id,
            TenantId,
        ):
            raise TypeError(
                "tenant_id must be TenantId"
            )

        if not isinstance(
            self.user_id,
            UserId,
        ):
            raise TypeError(
                "user_id must be UserId"
            )

        if type(self.token_digest) is not str:
            raise TypeError(
                "token_digest must be str"
            )

        if (
            len(self.token_digest)
            != _TOKEN_DIGEST_LENGTH
            or any(
                character not in hexdigits
                for character in self.token_digest
            )
            or self.token_digest
            != self.token_digest.lower()
        ):
            raise ValueError(
                "token_digest must be a lowercase SHA-256 digest"
            )

        if not isinstance(
            self.issued_at,
            datetime,
        ):
            raise TypeError(
                "issued_at must be datetime"
            )

        if not isinstance(
            self.expires_at,
            datetime,
        ):
            raise TypeError(
                "expires_at must be datetime"
            )

        if self.expires_at <= self.issued_at:
            raise ValueError(
                "expires_at must be after issued_at"
            )

        if (
            self.revoked_at is not None
            and not isinstance(
                self.revoked_at,
                datetime,
            )
        ):
            raise TypeError(
                "revoked_at must be datetime or None"
            )

        if (
            self.revoked_at is not None
            and self.revoked_at < self.issued_at
        ):
            raise ValueError(
                "revoked_at cannot precede issued_at"
            )

    def is_active_at(
        self,
        now: datetime,
    ) -> bool:
        if not isinstance(
            now,
            datetime,
        ):
            raise TypeError(
                "now must be datetime"
            )

        return (
            self.revoked_at is None
            and self.issued_at <= now
            and now < self.expires_at
        )


@dataclass(
    frozen=True,
    slots=True,
)
class IssuedApplicationSession:
    session_id: SessionId
    token: SessionToken = field(
        repr=False
    )
    principal: AuthenticatedPrincipal
    issued_at: datetime
    expires_at: datetime

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.session_id,
            SessionId,
        ):
            raise TypeError(
                "session_id must be SessionId"
            )

        if not isinstance(
            self.token,
            SessionToken,
        ):
            raise TypeError(
                "token must be SessionToken"
            )

        if not isinstance(
            self.principal,
            AuthenticatedPrincipal,
        ):
            raise TypeError(
                "principal must be AuthenticatedPrincipal"
            )

        if not isinstance(
            self.issued_at,
            datetime,
        ):
            raise TypeError(
                "issued_at must be datetime"
            )

        if not isinstance(
            self.expires_at,
            datetime,
        ):
            raise TypeError(
                "expires_at must be datetime"
            )

        if self.expires_at <= self.issued_at:
            raise ValueError(
                "expires_at must be after issued_at"
            )


class ApplicationSessionStore(Protocol):
    def add(
        self,
        session: ApplicationSession,
    ) -> ApplicationSession:
        ...

    def get_by_token_digest(
        self,
        token_digest: str,
    ) -> ApplicationSession | None:
        ...

    def update(
        self,
        session: ApplicationSession,
    ) -> ApplicationSession:
        ...


class ApplicationSessionClock(Protocol):
    def now(
        self,
    ) -> datetime:
        ...


class SessionTokenGenerator(Protocol):
    def new_session_id(
        self,
    ) -> SessionId:
        ...

    def new_token(
        self,
    ) -> SessionToken:
        ...


class PrincipalAuthenticator(Protocol):
    def authenticate(
        self,
        request: LoginRequest,
    ) -> AuthenticatedPrincipal:
        ...


class SecureSessionTokenGenerator:
    def new_session_id(
        self,
    ) -> SessionId:
        return SessionId(
            "SESSION-"
            + token_urlsafe(
                _SESSION_ID_BYTES
            )
        )

    def new_token(
        self,
    ) -> SessionToken:
        return SessionToken(
            "phx_"
            + token_urlsafe(
                _SESSION_TOKEN_BYTES
            )
        )


class SessionAuthenticationError(
    PermissionError,
):
    def __init__(
        self,
    ) -> None:
        super().__init__(
            "session authentication failed"
        )


class ApplicationSessionService:
    """
    Issue, authenticate, and revoke durable opaque sessions.
    """

    __slots__ = (
        "_clock",
        "_identities",
        "_lifetime",
        "_store",
        "_token_generator",
    )

    def __init__(
        self,
        *,
        store: ApplicationSessionStore,
        identities: AuthenticationIdentityReader,
        clock: ApplicationSessionClock,
        token_generator: SessionTokenGenerator | None = None,
        lifetime: timedelta = _DEFAULT_SESSION_LIFETIME,
    ) -> None:
        if store is None:
            raise TypeError(
                "store cannot be None"
            )

        if identities is None:
            raise TypeError(
                "identities cannot be None"
            )

        if clock is None:
            raise TypeError(
                "clock cannot be None"
            )

        if not isinstance(
            lifetime,
            timedelta,
        ):
            raise TypeError(
                "lifetime must be timedelta"
            )

        if lifetime <= timedelta(0):
            raise ValueError(
                "lifetime must be positive"
            )

        if lifetime > _MAXIMUM_SESSION_LIFETIME:
            raise ValueError(
                "lifetime cannot exceed 30 days"
            )

        self._store = store
        self._identities = identities
        self._clock = clock
        self._token_generator = (
            token_generator
            if token_generator is not None
            else SecureSessionTokenGenerator()
        )
        self._lifetime = lifetime

    def issue(
        self,
        principal: AuthenticatedPrincipal,
    ) -> IssuedApplicationSession:
        if not isinstance(
            principal,
            AuthenticatedPrincipal,
        ):
            raise TypeError(
                "principal must be AuthenticatedPrincipal"
            )

        identity = (
            self._identities
            .get_authentication_identity(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
            )
        )

        if (
            identity is None
            or identity.tenant_id
            != principal.tenant_id
            or identity.user_id
            != principal.user_id
            or not identity.tenant_enabled
            or not identity.user_enabled
        ):
            raise SessionAuthenticationError()

        resolved_principal = (
            AuthenticatedPrincipal(
                tenant_id=identity.tenant_id,
                user_id=identity.user_id,
                role=identity.role,
                account_ids=(
                    identity.account_ids
                ),
            )
        )

        now = self._clock.now()

        if not isinstance(
            now,
            datetime,
        ):
            raise TypeError(
                "clock.now() must return datetime"
            )

        session_id = (
            self._token_generator
            .new_session_id()
        )
        token = (
            self._token_generator
            .new_token()
        )
        expires_at = now + self._lifetime

        durable_session = ApplicationSession(
            session_id=session_id,
            tenant_id=(
                resolved_principal.tenant_id
            ),
            user_id=resolved_principal.user_id,
            token_digest=session_token_digest(
                token
            ),
            issued_at=now,
            expires_at=expires_at,
        )

        self._store.add(
            durable_session
        )

        return IssuedApplicationSession(
            session_id=session_id,
            token=token,
            principal=resolved_principal,
            issued_at=now,
            expires_at=expires_at,
        )

    def authenticate(
        self,
        token: SessionToken,
    ) -> AuthenticatedPrincipal:
        digest = session_token_digest(
            token
        )
        session = (
            self._store
            .get_by_token_digest(
                digest
            )
        )

        if session is None:
            raise SessionAuthenticationError()

        now = self._clock.now()

        if not session.is_active_at(
            now
        ):
            raise SessionAuthenticationError()

        identity = (
            self._identities
            .get_authentication_identity(
                tenant_id=(
                    session.tenant_id
                ),
                user_id=session.user_id,
            )
        )

        if (
            identity is None
            or identity.tenant_id
            != session.tenant_id
            or identity.user_id
            != session.user_id
            or not identity.tenant_enabled
            or not identity.user_enabled
        ):
            raise SessionAuthenticationError()

        return AuthenticatedPrincipal(
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            role=identity.role,
            account_ids=identity.account_ids,
        )

    def revoke(
        self,
        token: SessionToken,
    ) -> bool:
        digest = session_token_digest(
            token
        )
        session = (
            self._store
            .get_by_token_digest(
                digest
            )
        )

        if (
            session is None
            or session.revoked_at is not None
        ):
            return False

        revoked = replace(
            session,
            revoked_at=self._clock.now(),
        )
        self._store.update(
            revoked
        )

        return True


class ApplicationLoginService:
    """
    Authenticate a password and issue one application session.
    """

    __slots__ = (
        "_authentication",
        "_sessions",
    )

    def __init__(
        self,
        *,
        authentication: PrincipalAuthenticator,
        sessions: ApplicationSessionService,
    ) -> None:
        if authentication is None:
            raise TypeError(
                "authentication cannot be None"
            )

        if sessions is None:
            raise TypeError(
                "sessions cannot be None"
            )

        self._authentication = authentication
        self._sessions = sessions

    def login(
        self,
        request: LoginRequest,
    ) -> IssuedApplicationSession:
        principal = (
            self._authentication
            .authenticate(
                request
            )
        )

        return self._sessions.issue(
            principal
        )


__all__ = [
    "ApplicationLoginService",
    "ApplicationSession",
    "ApplicationSessionClock",
    "ApplicationSessionService",
    "ApplicationSessionStore",
    "IssuedApplicationSession",
    "PrincipalAuthenticator",
    "SecureSessionTokenGenerator",
    "SessionAuthenticationError",
    "SessionId",
    "SessionToken",
    "SessionTokenGenerator",
    "session_token_digest",
]
