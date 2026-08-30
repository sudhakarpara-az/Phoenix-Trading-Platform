"""
M15 persistence adapters for password authentication.

These adapters translate the existing durable tenant, user,
membership, and password-credential records into the transport-neutral
authentication types owned by ``src.api.authentication``.

They do not verify passwords, issue sessions or tokens, authorize
requests, expose HTTP routes, or mutate persistence.
"""

from __future__ import annotations

from src.account.account_types import (
    BrokerAccountId,
)
from src.api.access_control import (
    TenantId,
    UserId,
    UserRole,
)
from src.api.authentication import (
    AuthenticationIdentity,
    PasswordCredential,
)
from src.database.repositories.interfaces import (
    TenantRepository,
    UserBrokerAccountMembershipRepository,
    UserPasswordCredentialRepository,
    UserRepository,
)


class RepositoryAuthenticationIdentityReader:
    """
    Resolve one authentication identity from existing repositories.

    Missing or inconsistent durable state returns ``None`` so the
    authentication service can fail closed with its generic error.
    """

    __slots__ = (
        "_memberships",
        "_tenants",
        "_users",
    )

    def __init__(
        self,
        *,
        tenants: TenantRepository,
        users: UserRepository,
        memberships: UserBrokerAccountMembershipRepository,
    ) -> None:
        if tenants is None:
            raise TypeError(
                "tenants cannot be None"
            )

        if users is None:
            raise TypeError(
                "users cannot be None"
            )

        if memberships is None:
            raise TypeError(
                "memberships cannot be None"
            )

        self._tenants = tenants
        self._users = users
        self._memberships = memberships

    def get_authentication_identity(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
    ) -> AuthenticationIdentity | None:
        if not isinstance(
            tenant_id,
            TenantId,
        ):
            raise TypeError(
                "tenant_id must be TenantId"
            )

        if not isinstance(
            user_id,
            UserId,
        ):
            raise TypeError(
                "user_id must be UserId"
            )

        tenant = self._tenants.get(
            tenant_id.value
        )
        user = self._users.get(
            tenant_id=tenant_id.value,
            user_id=user_id.value,
        )

        if tenant is None or user is None:
            return None

        if (
            tenant.tenant_id != tenant_id.value
            or user.tenant_id != tenant_id.value
            or user.user_id != user_id.value
            or type(tenant.enabled) is not bool
            or type(user.enabled) is not bool
        ):
            return None

        memberships = (
            self._memberships.list_for_user(
                tenant_id=tenant_id.value,
                user_id=user_id.value,
            )
        )

        try:
            role = UserRole(
                user.role
            )
            account_ids = tuple(
                BrokerAccountId(
                    membership.account_id
                )
                for membership in memberships
                if membership.broker == "DHAN"
            )

            if len(account_ids) != len(
                memberships
            ):
                return None

            return AuthenticationIdentity(
                tenant_id=tenant_id,
                user_id=user_id,
                role=role,
                tenant_enabled=tenant.enabled,
                user_enabled=user.enabled,
                account_ids=account_ids,
            )

        except (
            TypeError,
            ValueError,
        ):
            return None


class RepositoryPasswordCredentialReader:
    """
    Translate one durable hash record into a T03 credential value.
    """

    __slots__ = (
        "_credentials",
    )

    def __init__(
        self,
        *,
        credentials: UserPasswordCredentialRepository,
    ) -> None:
        if credentials is None:
            raise TypeError(
                "credentials cannot be None"
            )

        self._credentials = credentials

    def get_password_credential(
        self,
        *,
        tenant_id: TenantId,
        user_id: UserId,
    ) -> PasswordCredential | None:
        if not isinstance(
            tenant_id,
            TenantId,
        ):
            raise TypeError(
                "tenant_id must be TenantId"
            )

        if not isinstance(
            user_id,
            UserId,
        ):
            raise TypeError(
                "user_id must be UserId"
            )

        record = self._credentials.get(
            tenant_id=tenant_id.value,
            user_id=user_id.value,
        )

        if record is None:
            return None

        if (
            record.tenant_id
            != tenant_id.value
            or record.user_id
            != user_id.value
        ):
            return None

        try:
            return PasswordCredential(
                tenant_id=tenant_id,
                user_id=user_id,
                password_hash=(
                    record.password_hash
                ),
            )

        except (
            TypeError,
            ValueError,
        ):
            return None


__all__ = [
    "RepositoryAuthenticationIdentityReader",
    "RepositoryPasswordCredentialReader",
]
