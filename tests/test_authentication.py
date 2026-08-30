"""
M15-T03 password-authentication foundation tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.account.account_types import BrokerAccountId
from src.api.access_control import (
    TenantId,
    UserId,
    UserRole,
)
from src.api.authentication import (
    AuthenticationError,
    AuthenticationIdentity,
    AuthenticationService,
    LoginRequest,
    PasswordCredential,
    Pbkdf2PasswordHasher,
)


PASSWORD = "correct horse battery staple"


@dataclass
class _IdentityReader:
    identity: AuthenticationIdentity | None
    calls: int = 0

    def get_authentication_identity(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
    ) -> AuthenticationIdentity | None:
        self.calls += 1
        return self.identity


@dataclass
class _CredentialReader:
    credential: PasswordCredential | None
    calls: int = 0

    def get_password_credential(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
    ) -> PasswordCredential | None:
        self.calls += 1
        return self.credential


class _PasswordHasher:
    def __init__(
        self,
        *,
        matches: bool,
    ) -> None:
        self.matches = matches
        self.verified_hashes: list[str] = []

    def hash_password(
        self,
        password: str,
    ) -> str:
        return "generated-dummy-hash"

    def verify_password(
        self,
        *,
        password: str,
        encoded_hash: str,
    ) -> bool:
        self.verified_hashes.append(
            encoded_hash
        )
        return self.matches


def _identity(
    *,
    tenant_enabled: bool = True,
    user_enabled: bool = True,
) -> AuthenticationIdentity:
    return AuthenticationIdentity(
        tenant_id=TenantId("TENANT-A"),
        user_id=UserId("USER-001"),
        role=UserRole.USER,
        tenant_enabled=tenant_enabled,
        user_enabled=user_enabled,
        account_ids=(
            BrokerAccountId("DHAN-001"),
        ),
    )


def _credential(
    *,
    tenant_id: str = "TENANT-A",
    user_id: str = "USER-001",
) -> PasswordCredential:
    return PasswordCredential(
        tenant_id=TenantId(tenant_id),
        user_id=UserId(user_id),
        password_hash="stored-password-hash",
    )


def _request(
) -> LoginRequest:
    return LoginRequest(
        tenant_id=TenantId("TENANT-A"),
        user_id=UserId("USER-001"),
        password=PASSWORD,
    )


def _service(
    *,
    identity: AuthenticationIdentity | None = None,
    credential: PasswordCredential | None = None,
    matches: bool = True,
) -> tuple[
    AuthenticationService,
    _IdentityReader,
    _CredentialReader,
    _PasswordHasher,
]:
    identities = _IdentityReader(
        identity=(
            identity
            if identity is not None
            else _identity()
        )
    )
    credentials = _CredentialReader(
        credential=(
            credential
            if credential is not None
            else _credential()
        )
    )
    hasher = _PasswordHasher(
        matches=matches
    )

    return (
        AuthenticationService(
            identities=identities,
            credentials=credentials,
            password_hasher=hasher,
            dummy_password_hash=(
                "explicit-dummy-hash"
            ),
        ),
        identities,
        credentials,
        hasher,
    )


def test_pbkdf2_hash_round_trip_and_random_salt(
) -> None:
    hasher = Pbkdf2PasswordHasher(
        iterations=100_000
    )

    first = hasher.hash_password(
        PASSWORD
    )
    second = hasher.hash_password(
        PASSWORD
    )

    assert first != second
    assert PASSWORD not in first
    assert first.startswith(
        "pbkdf2_sha256$100000$"
    )
    assert hasher.verify_password(
        password=PASSWORD,
        encoded_hash=first,
    )
    assert not hasher.verify_password(
        password="wrong password",
        encoded_hash=first,
    )


@pytest.mark.parametrize(
    "encoded_hash",
    [
        "",
        "not-a-password-hash",
        "pbkdf2_sha512$100000$salt$digest",
        "pbkdf2_sha256$99999$salt$digest",
        "pbkdf2_sha256$invalid$salt$digest",
    ],
)
def test_pbkdf2_rejects_malformed_hashes(
    encoded_hash: str,
) -> None:
    assert not (
        Pbkdf2PasswordHasher(
            iterations=100_000
        ).verify_password(
            password=PASSWORD,
            encoded_hash=encoded_hash,
        )
    )


def test_pbkdf2_reports_changed_work_factor(
) -> None:
    old = Pbkdf2PasswordHasher(
        iterations=100_000
    )
    current = Pbkdf2PasswordHasher(
        iterations=110_000
    )
    encoded = old.hash_password(
        PASSWORD
    )

    assert not old.needs_rehash(
        encoded
    )
    assert current.needs_rehash(
        encoded
    )


def test_login_request_repr_hides_password(
) -> None:
    request = _request()

    assert PASSWORD not in repr(
        request
    )


def test_successful_login_builds_existing_principal(
) -> None:
    (
        service,
        identities,
        credentials,
        hasher,
    ) = _service()

    principal = service.authenticate(
        _request()
    )

    assert principal.tenant_id == TenantId(
        "TENANT-A"
    )
    assert principal.user_id == UserId(
        "USER-001"
    )
    assert principal.role is UserRole.USER
    assert principal.account_ids == (
        BrokerAccountId("DHAN-001"),
    )
    assert identities.calls == 1
    assert credentials.calls == 1
    assert hasher.verified_hashes == [
        "stored-password-hash"
    ]


@pytest.mark.parametrize(
    ("identity", "matches"),
    [
        (
            _identity(
                tenant_enabled=False
            ),
            True,
        ),
        (
            _identity(
                user_enabled=False
            ),
            True,
        ),
        (
            _identity(),
            False,
        ),
    ],
)
def test_rejected_login_uses_generic_error(
    identity: AuthenticationIdentity,
    matches: bool,
) -> None:
    service, _, _, _ = _service(
        identity=identity,
        matches=matches,
    )

    with pytest.raises(
        AuthenticationError,
        match="^authentication failed$",
    ):
        service.authenticate(
            _request()
        )


def test_missing_identity_still_verifies_dummy_hash(
) -> None:
    identities = _IdentityReader(
        identity=None
    )
    credentials = _CredentialReader(
        credential=None
    )
    hasher = _PasswordHasher(
        matches=False
    )
    service = AuthenticationService(
        identities=identities,
        credentials=credentials,
        password_hasher=hasher,
        dummy_password_hash=(
            "explicit-dummy-hash"
        ),
    )

    with pytest.raises(
        AuthenticationError,
        match="^authentication failed$",
    ):
        service.authenticate(
            _request()
        )

    assert identities.calls == 1
    assert credentials.calls == 1
    assert hasher.verified_hashes == [
        "explicit-dummy-hash"
    ]


def test_mismatched_credential_binding_fails_closed(
) -> None:
    service, _, _, _ = _service(
        credential=_credential(
            user_id="USER-OTHER"
        )
    )

    with pytest.raises(
        AuthenticationError,
        match="^authentication failed$",
    ):
        service.authenticate(
            _request()
        )


def test_duplicate_account_scope_is_rejected(
) -> None:
    account_id = BrokerAccountId(
        "DHAN-001"
    )

    with pytest.raises(
        ValueError,
        match=(
            "account_ids cannot contain duplicates"
        ),
    ):
        AuthenticationIdentity(
            tenant_id=TenantId("TENANT-A"),
            user_id=UserId("USER-001"),
            role=UserRole.USER,
            tenant_enabled=True,
            user_enabled=True,
            account_ids=(
                account_id,
                account_id,
            ),
        )
