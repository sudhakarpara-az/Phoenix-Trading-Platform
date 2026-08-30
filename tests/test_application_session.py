"""
M15-T05 application login and session lifecycle tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
)

import pytest

from src.account.account_types import (
    BrokerAccountId,
)
from src.api.access_control import (
    AuthenticatedPrincipal,
    TenantId,
    UserId,
    UserRole,
)
from src.api.application_session import (
    ApplicationLoginService,
    ApplicationSession,
    ApplicationSessionService,
    SessionAuthenticationError,
    SessionId,
    SessionToken,
    session_token_digest,
)
from src.api.authentication import (
    AuthenticationError,
    AuthenticationIdentity,
    LoginRequest,
)


NOW = datetime(
    2026,
    8,
    30,
    17,
    0,
)


@dataclass
class _Clock:
    value: datetime = NOW

    def now(
        self,
    ) -> datetime:
        return self.value


class _TokenGenerator:
    def __init__(
        self,
    ) -> None:
        self.counter = 0

    def new_session_id(
        self,
    ) -> SessionId:
        self.counter += 1
        return SessionId(
            f"SESSION-{self.counter}"
        )

    def new_token(
        self,
    ) -> SessionToken:
        return SessionToken(
            f"phx_test_token_{self.counter}"
        )


class _Store:
    def __init__(
        self,
    ) -> None:
        self.by_digest: dict[
            str,
            ApplicationSession,
        ] = {}

    def add(
        self,
        session: ApplicationSession,
    ) -> ApplicationSession:
        self.by_digest[
            session.token_digest
        ] = session
        return session

    def get_by_token_digest(
        self,
        token_digest: str,
    ) -> ApplicationSession | None:
        return self.by_digest.get(
            token_digest
        )

    def update(
        self,
        session: ApplicationSession,
    ) -> ApplicationSession:
        self.by_digest[
            session.token_digest
        ] = session
        return session


@dataclass
class _IdentityReader:
    identity: AuthenticationIdentity | None

    def get_authentication_identity(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
    ) -> AuthenticationIdentity | None:
        return self.identity


@dataclass
class _Authenticator:
    principal: AuthenticatedPrincipal | None
    calls: int = 0

    def authenticate(
        self,
        request: LoginRequest,
    ) -> AuthenticatedPrincipal:
        self.calls += 1

        if self.principal is None:
            raise AuthenticationError()

        return self.principal


def _principal(
    *,
    role: UserRole = UserRole.USER,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=TenantId("TENANT-A"),
        user_id=UserId("USER-001"),
        role=role,
        account_ids=(
            BrokerAccountId("DHAN-001"),
        ),
    )


def _identity(
    *,
    tenant_enabled: bool = True,
    user_enabled: bool = True,
    role: UserRole = UserRole.USER,
) -> AuthenticationIdentity:
    return AuthenticationIdentity(
        tenant_id=TenantId("TENANT-A"),
        user_id=UserId("USER-001"),
        role=role,
        tenant_enabled=tenant_enabled,
        user_enabled=user_enabled,
        account_ids=(
            BrokerAccountId("DHAN-001"),
        ),
    )


def _service(
    *,
    clock: _Clock | None = None,
    identity: AuthenticationIdentity | None = None,
) -> tuple[
    ApplicationSessionService,
    _Store,
    _Clock,
]:
    resolved_clock = (
        clock
        if clock is not None
        else _Clock()
    )
    store = _Store()

    return (
        ApplicationSessionService(
            store=store,
            identities=_IdentityReader(
                identity=(
                    identity
                    if identity is not None
                    else _identity()
                )
            ),
            clock=resolved_clock,
            token_generator=(
                _TokenGenerator()
            ),
            lifetime=timedelta(
                hours=8
            ),
        ),
        store,
        resolved_clock,
    )


def test_session_token_repr_hides_raw_value(
) -> None:
    raw = "phx_secret_bearer_token"
    token = SessionToken(
        raw
    )

    assert raw not in repr(
        token
    )
    assert session_token_digest(
        token
    ) == session_token_digest(
        token
    )


def test_issue_persists_only_token_digest(
) -> None:
    service, store, _ = _service()

    issued = service.issue(
        _principal()
    )
    digest = session_token_digest(
        issued.token
    )
    stored = store.by_digest[
        digest
    ]

    assert stored.token_digest == digest
    assert issued.token.value not in repr(
        stored
    )
    assert issued.token.value != digest
    assert issued.expires_at == (
        NOW + timedelta(hours=8)
    )


def test_active_session_authenticates_current_identity(
) -> None:
    service, _, _ = _service(
        identity=_identity(
            role=UserRole.ADMIN
        )
    )
    issued = service.issue(
        _principal(
            role=UserRole.USER
        )
    )

    resolved = service.authenticate(
        issued.token
    )

    assert resolved.role is UserRole.ADMIN
    assert resolved.account_ids == (
        BrokerAccountId("DHAN-001"),
    )


def test_unknown_token_fails_generically(
) -> None:
    service, _, _ = _service()

    with pytest.raises(
        SessionAuthenticationError,
        match=(
            "^session authentication failed$"
        ),
    ):
        service.authenticate(
            SessionToken("phx_unknown")
        )


def test_expired_session_fails_generically(
) -> None:
    service, _, clock = _service()
    issued = service.issue(
        _principal()
    )
    clock.value = issued.expires_at

    with pytest.raises(
        SessionAuthenticationError,
        match=(
            "^session authentication failed$"
        ),
    ):
        service.authenticate(
            issued.token
        )


@pytest.mark.parametrize(
    "identity",
    [
        _identity(
            tenant_enabled=False
        ),
        _identity(
            user_enabled=False
        ),
    ],
)
def test_disabled_identity_invalidates_existing_session(
    identity: AuthenticationIdentity,
) -> None:
    reader = _IdentityReader(
        identity=_identity()
    )
    service = ApplicationSessionService(
        store=_Store(),
        identities=reader,
        clock=_Clock(),
        token_generator=(
            _TokenGenerator()
        ),
    )
    issued = service.issue(
        _principal()
    )
    reader.identity = identity

    with pytest.raises(
        SessionAuthenticationError,
        match=(
            "^session authentication failed$"
        ),
    ):
        service.authenticate(
            issued.token
        )


def test_revoke_is_idempotent_and_blocks_session(
) -> None:
    service, store, _ = _service()
    issued = service.issue(
        _principal()
    )

    assert service.revoke(
        issued.token
    )
    assert not service.revoke(
        issued.token
    )
    assert (
        store.by_digest[
            session_token_digest(
                issued.token
            )
        ].revoked_at
        == NOW
    )

    with pytest.raises(
        SessionAuthenticationError
    ):
        service.authenticate(
            issued.token
        )


def test_login_issues_session_only_after_authentication(
) -> None:
    sessions, store, _ = _service()
    authenticator = _Authenticator(
        principal=_principal()
    )
    login = ApplicationLoginService(
        authentication=authenticator,
        sessions=sessions,
    )

    issued = login.login(
        LoginRequest(
            tenant_id=TenantId("TENANT-A"),
            user_id=UserId("USER-001"),
            password="valid password",
        )
    )

    assert authenticator.calls == 1
    assert len(store.by_digest) == 1
    assert issued.principal == _principal()


def test_failed_login_does_not_issue_session(
) -> None:
    sessions, store, _ = _service()
    login = ApplicationLoginService(
        authentication=_Authenticator(
            principal=None
        ),
        sessions=sessions,
    )

    with pytest.raises(
        AuthenticationError
    ):
        login.login(
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

    assert store.by_digest == {}


@pytest.mark.parametrize(
    "lifetime",
    [
        timedelta(0),
        timedelta(seconds=-1),
        timedelta(days=31),
    ],
)
def test_invalid_session_lifetime_is_rejected(
    lifetime: timedelta,
) -> None:
    with pytest.raises(
        ValueError
    ):
        ApplicationSessionService(
            store=_Store(),
            identities=_IdentityReader(
                identity=_identity()
            ),
            clock=_Clock(),
            token_generator=(
                _TokenGenerator()
            ),
            lifetime=lifetime,
        )
