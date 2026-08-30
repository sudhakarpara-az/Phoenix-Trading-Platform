"""
Phoenix M15 password-authentication foundation.

This module owns transport-neutral credential verification only. It
does not persist credentials, issue sessions or tokens, expose HTTP
routes, or perform authorization decisions.

Authentication fails closed with one generic external error. Tenant
and user lifecycle state is resolved by an injected identity source;
credential persistence is supplied through a separate injected port.
"""

from __future__ import annotations

from base64 import (
    urlsafe_b64decode,
    urlsafe_b64encode,
)
from dataclasses import (
    dataclass,
    field,
)
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_bytes
from typing import Protocol

from src.account.account_types import BrokerAccountId
from src.api.access_control import (
    AuthenticatedPrincipal,
    TenantId,
    UserId,
    UserRole,
)


_PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
_PASSWORD_HASH_DIGEST = "sha256"
_DEFAULT_ITERATIONS = 600_000
_MINIMUM_ITERATIONS = 100_000
_MAXIMUM_VERIFY_ITERATIONS = 2_000_000
_SALT_BYTES = 16
_DERIVED_KEY_BYTES = 32


def _encode_bytes(
    value: bytes,
) -> str:
    return (
        urlsafe_b64encode(value)
        .decode("ascii")
        .rstrip("=")
    )


def _decode_bytes(
    value: str,
) -> bytes:
    padding = "=" * (
        (-len(value)) % 4
    )
    return urlsafe_b64decode(
        value + padding
    )


class PasswordHasher(Protocol):
    """
    Password hashing boundary consumed by authentication.
    """

    def hash_password(
        self,
        password: str,
    ) -> str:
        ...

    def verify_password(
        self,
        *,
        password: str,
        encoded_hash: str,
    ) -> bool:
        ...


class Pbkdf2PasswordHasher:
    """
    Versioned PBKDF2-HMAC-SHA256 password hashing.

    Every password receives a cryptographically random salt. Encoded
    hashes carry their work factor so it can be increased later
    without invalidating existing credentials.
    """

    __slots__ = (
        "_iterations",
    )

    def __init__(
        self,
        *,
        iterations: int = _DEFAULT_ITERATIONS,
    ) -> None:
        if type(iterations) is not int:
            raise TypeError(
                "iterations must be int"
            )

        if iterations < _MINIMUM_ITERATIONS:
            raise ValueError(
                "iterations must be at least "
                f"{_MINIMUM_ITERATIONS}"
            )

        if iterations > _MAXIMUM_VERIFY_ITERATIONS:
            raise ValueError(
                "iterations cannot exceed "
                f"{_MAXIMUM_VERIFY_ITERATIONS}"
            )

        self._iterations = iterations

    @property
    def iterations(
        self,
    ) -> int:
        return self._iterations

    def hash_password(
        self,
        password: str,
    ) -> str:
        if type(password) is not str:
            raise TypeError(
                "password must be str"
            )

        if not password:
            raise ValueError(
                "password cannot be empty"
            )

        salt = token_bytes(
            _SALT_BYTES
        )
        derived_key = pbkdf2_hmac(
            _PASSWORD_HASH_DIGEST,
            password.encode("utf-8"),
            salt,
            self._iterations,
            dklen=_DERIVED_KEY_BYTES,
        )

        return "$".join(
            (
                _PASSWORD_HASH_SCHEME,
                str(self._iterations),
                _encode_bytes(salt),
                _encode_bytes(derived_key),
            )
        )

    def verify_password(
        self,
        *,
        password: str,
        encoded_hash: str,
    ) -> bool:
        if type(password) is not str:
            raise TypeError(
                "password must be str"
            )

        if type(encoded_hash) is not str:
            raise TypeError(
                "encoded_hash must be str"
            )

        try:
            (
                scheme,
                encoded_iterations,
                encoded_salt,
                encoded_derived_key,
            ) = encoded_hash.split("$")

            if scheme != _PASSWORD_HASH_SCHEME:
                return False

            iterations = int(
                encoded_iterations
            )

            if not (
                _MINIMUM_ITERATIONS
                <= iterations
                <= _MAXIMUM_VERIFY_ITERATIONS
            ):
                return False

            salt = _decode_bytes(
                encoded_salt
            )
            expected = _decode_bytes(
                encoded_derived_key
            )

            if len(salt) < _SALT_BYTES:
                return False

            if len(expected) != _DERIVED_KEY_BYTES:
                return False

        except (
            TypeError,
            ValueError,
        ):
            return False

        actual = pbkdf2_hmac(
            _PASSWORD_HASH_DIGEST,
            password.encode("utf-8"),
            salt,
            iterations,
            dklen=len(expected),
        )

        return compare_digest(
            actual,
            expected,
        )

    def needs_rehash(
        self,
        encoded_hash: str,
    ) -> bool:
        if type(encoded_hash) is not str:
            raise TypeError(
                "encoded_hash must be str"
            )

        try:
            (
                scheme,
                encoded_iterations,
                _encoded_salt,
                _encoded_derived_key,
            ) = encoded_hash.split("$")

            return (
                scheme != _PASSWORD_HASH_SCHEME
                or int(encoded_iterations)
                != self._iterations
            )

        except (
            TypeError,
            ValueError,
        ):
            return True


@dataclass(
    frozen=True,
    slots=True,
)
class LoginRequest:
    """
    One transport-neutral password login attempt.
    """

    tenant_id: TenantId
    user_id: UserId
    password: str = field(
        repr=False
    )

    def __post_init__(
        self,
    ) -> None:
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

        if type(self.password) is not str:
            raise TypeError(
                "password must be str"
            )

        if not self.password:
            raise ValueError(
                "password cannot be empty"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class AuthenticationIdentity:
    """
    Persisted identity state needed for one login decision.
    """

    tenant_id: TenantId
    user_id: UserId
    role: UserRole
    tenant_enabled: bool
    user_enabled: bool
    account_ids: tuple[
        BrokerAccountId,
        ...
    ] = ()

    def __post_init__(
        self,
    ) -> None:
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

        if not isinstance(
            self.role,
            UserRole,
        ):
            raise TypeError(
                "role must be UserRole"
            )

        if type(self.tenant_enabled) is not bool:
            raise TypeError(
                "tenant_enabled must be bool"
            )

        if type(self.user_enabled) is not bool:
            raise TypeError(
                "user_enabled must be bool"
            )

        if type(self.account_ids) is not tuple:
            raise TypeError(
                "account_ids must be tuple"
            )

        seen: set[
            BrokerAccountId
        ] = set()

        for account_id in self.account_ids:
            if not isinstance(
                account_id,
                BrokerAccountId,
            ):
                raise TypeError(
                    "account_ids must contain "
                    "BrokerAccountId values"
                )

            if account_id in seen:
                raise ValueError(
                    "account_ids cannot contain duplicates"
                )

            seen.add(
                account_id
            )


@dataclass(
    frozen=True,
    slots=True,
)
class PasswordCredential:
    """
    Stored password hash bound to one tenant-scoped user.
    """

    tenant_id: TenantId
    user_id: UserId
    password_hash: str = field(
        repr=False
    )

    def __post_init__(
        self,
    ) -> None:
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

        if type(self.password_hash) is not str:
            raise TypeError(
                "password_hash must be str"
            )

        if not self.password_hash:
            raise ValueError(
                "password_hash cannot be empty"
            )


class AuthenticationIdentityReader(Protocol):
    def get_authentication_identity(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
    ) -> AuthenticationIdentity | None:
        ...


class PasswordCredentialReader(Protocol):
    def get_password_credential(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
    ) -> PasswordCredential | None:
        ...


class AuthenticationError(
    PermissionError,
):
    """
    Generic failure that does not disclose identity state.
    """

    def __init__(
        self,
    ) -> None:
        super().__init__(
            "authentication failed"
        )


class AuthenticationService:
    """
    Fail-closed password authentication service.

    Missing identities and missing credentials still execute the
    password-verification boundary using a dummy hash. All rejected
    attempts expose the same AuthenticationError.
    """

    __slots__ = (
        "_credentials",
        "_dummy_password_hash",
        "_identities",
        "_password_hasher",
    )

    def __init__(
        self,
        *,
        identities: AuthenticationIdentityReader,
        credentials: PasswordCredentialReader,
        password_hasher: PasswordHasher,
        dummy_password_hash: str | None = None,
    ) -> None:
        if identities is None:
            raise TypeError(
                "identities cannot be None"
            )

        if credentials is None:
            raise TypeError(
                "credentials cannot be None"
            )

        if password_hasher is None:
            raise TypeError(
                "password_hasher cannot be None"
            )

        resolved_dummy_hash = (
            dummy_password_hash
            if dummy_password_hash is not None
            else password_hasher.hash_password(
                _encode_bytes(
                    token_bytes(32)
                )
            )
        )

        if type(resolved_dummy_hash) is not str:
            raise TypeError(
                "dummy_password_hash must be str"
            )

        if not resolved_dummy_hash:
            raise ValueError(
                "dummy_password_hash cannot be empty"
            )

        self._identities = identities
        self._credentials = credentials
        self._password_hasher = password_hasher
        self._dummy_password_hash = (
            resolved_dummy_hash
        )

    def authenticate(
        self,
        request: LoginRequest,
    ) -> AuthenticatedPrincipal:
        if not isinstance(
            request,
            LoginRequest,
        ):
            raise TypeError(
                "request must be LoginRequest"
            )

        identity = (
            self._identities
            .get_authentication_identity(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
            )
        )
        credential = (
            self._credentials
            .get_password_credential(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
            )
        )

        encoded_hash = (
            credential.password_hash
            if credential is not None
            else self._dummy_password_hash
        )
        password_matches = (
            self._password_hasher
            .verify_password(
                password=request.password,
                encoded_hash=encoded_hash,
            )
        )

        valid_binding = (
            identity is not None
            and credential is not None
            and identity.tenant_id
            == request.tenant_id
            and identity.user_id
            == request.user_id
            and credential.tenant_id
            == request.tenant_id
            and credential.user_id
            == request.user_id
        )

        if (
            not valid_binding
            or identity is None
            or not identity.tenant_enabled
            or not identity.user_enabled
            or not password_matches
        ):
            raise AuthenticationError()

        return AuthenticatedPrincipal(
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
            role=identity.role,
            account_ids=identity.account_ids,
        )


__all__ = [
    "AuthenticationError",
    "AuthenticationIdentity",
    "AuthenticationIdentityReader",
    "AuthenticationService",
    "LoginRequest",
    "PasswordCredential",
    "PasswordCredentialReader",
    "PasswordHasher",
    "Pbkdf2PasswordHasher",
]
