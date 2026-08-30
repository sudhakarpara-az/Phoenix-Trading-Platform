"""
Phoenix M15 identity, RBAC, and tenant-isolation foundation.

This module owns transport-neutral authorization policy only. It does
not authenticate credentials, issue sessions or tokens, query a
repository, expose HTTP routes, or perform trading operations.

Authorization is deny-by-default. Every decision is tenant-scoped,
and account-scoped permissions require an explicit broker account.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.account.account_types import BrokerAccountId


@dataclass(
    frozen=True,
    slots=True,
)
class TenantId:
    """
    Stable Phoenix identity for one tenant.
    """

    value: str

    def __post_init__(
        self,
    ) -> None:
        if type(self.value) is not str:
            raise TypeError(
                "tenant id must be str"
            )

        normalized = self.value.strip()

        if not normalized:
            raise ValueError(
                "tenant id cannot be empty"
            )

        if normalized != self.value:
            object.__setattr__(
                self,
                "value",
                normalized,
            )

    def __str__(
        self,
    ) -> str:
        return self.value


@dataclass(
    frozen=True,
    slots=True,
)
class UserId:
    """
    Stable Phoenix identity for one application user.
    """

    value: str

    def __post_init__(
        self,
    ) -> None:
        if type(self.value) is not str:
            raise TypeError(
                "user id must be str"
            )

        normalized = self.value.strip()

        if not normalized:
            raise ValueError(
                "user id cannot be empty"
            )

        if normalized != self.value:
            object.__setattr__(
                self,
                "value",
                normalized,
            )

    def __str__(
        self,
    ) -> str:
        return self.value


class UserRole(
    str,
    Enum,
):
    """
    M15 application roles.

    ADMIN is tenant-scoped. It does not bypass tenant isolation.
    """

    ADMIN = "ADMIN"
    USER = "USER"


class AccessPermission(
    str,
    Enum,
):
    """
    Explicit M15 application permissions.
    """

    READ_OPERATOR_DATA = "READ_OPERATOR_DATA"
    READ_REPORTS = "READ_REPORTS"
    CONTROL_TRADING = "CONTROL_TRADING"
    MANAGE_USERS = "MANAGE_USERS"
    MANAGE_TENANT = "MANAGE_TENANT"


class AccessDeniedReason(
    str,
    Enum,
):
    """
    Internal reason for one fail-closed authorization denial.
    """

    TENANT_MISMATCH = "TENANT_MISMATCH"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ACCOUNT_REQUIRED = "ACCOUNT_REQUIRED"
    ACCOUNT_SCOPE_MISMATCH = "ACCOUNT_SCOPE_MISMATCH"


@dataclass(
    frozen=True,
    slots=True,
)
class AuthenticatedPrincipal:
    """
    Authenticated application identity supplied to authorization.

    Authentication/session ownership is introduced by a later M15
    slice. This value contains no password, credential, or token.
    """

    user_id: UserId
    tenant_id: TenantId
    role: UserRole
    account_ids: tuple[
        BrokerAccountId,
        ...
    ] = ()

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.user_id,
            UserId,
        ):
            raise TypeError(
                "user_id must be UserId"
            )

        if not isinstance(
            self.tenant_id,
            TenantId,
        ):
            raise TypeError(
                "tenant_id must be TenantId"
            )

        if not isinstance(
            self.role,
            UserRole,
        ):
            raise TypeError(
                "role must be UserRole"
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

    def has_account(
        self,
        account_id: BrokerAccountId,
    ) -> bool:
        if not isinstance(
            account_id,
            BrokerAccountId,
        ):
            raise TypeError(
                "account_id must be BrokerAccountId"
            )

        return account_id in self.account_ids


@dataclass(
    frozen=True,
    slots=True,
)
class AccessDecision:
    """
    Immutable result of one M15 authorization decision.
    """

    allowed: bool
    reason: AccessDeniedReason | None = None

    def __post_init__(
        self,
    ) -> None:
        if type(self.allowed) is not bool:
            raise TypeError(
                "allowed must be bool"
            )

        if self.allowed and self.reason is not None:
            raise ValueError(
                "allowed decision cannot have a denial reason"
            )

        if not self.allowed and self.reason is None:
            raise ValueError(
                "denied decision requires a reason"
            )


class AccessDeniedError(
    PermissionError,
):
    """
    Generic external error for a denied authorization decision.
    """

    def __init__(
        self,
        *,
        reason: AccessDeniedReason,
    ) -> None:
        if not isinstance(
            reason,
            AccessDeniedReason,
        ):
            raise TypeError(
                "reason must be AccessDeniedReason"
            )

        super().__init__(
            "access denied"
        )
        self._reason = reason

    @property
    def reason(
        self,
    ) -> AccessDeniedReason:
        return self._reason


_ROLE_PERMISSIONS: dict[
    UserRole,
    frozenset[AccessPermission],
] = {
    UserRole.ADMIN: frozenset(
        AccessPermission
    ),
    UserRole.USER: frozenset(
        {
            AccessPermission.READ_OPERATOR_DATA,
            AccessPermission.READ_REPORTS,
            AccessPermission.CONTROL_TRADING,
        }
    ),
}

_ACCOUNT_SCOPED_PERMISSIONS = frozenset(
    {
        AccessPermission.READ_OPERATOR_DATA,
        AccessPermission.READ_REPORTS,
        AccessPermission.CONTROL_TRADING,
    }
)


class RbacPolicy:
    """
    Stateless, deny-by-default M15 authorization policy.

    ADMIN may access any account that is already resolved inside its
    tenant. USER must additionally hold the exact account scope.
    Neither role may cross a tenant boundary.
    """

    def evaluate(
        self,
        *,
        principal: AuthenticatedPrincipal,
        permission: AccessPermission,
        tenant_id: TenantId,
        account_id: BrokerAccountId | None = None,
    ) -> AccessDecision:
        if not isinstance(
            principal,
            AuthenticatedPrincipal,
        ):
            raise TypeError(
                "principal must be AuthenticatedPrincipal"
            )

        if not isinstance(
            permission,
            AccessPermission,
        ):
            raise TypeError(
                "permission must be AccessPermission"
            )

        if not isinstance(
            tenant_id,
            TenantId,
        ):
            raise TypeError(
                "tenant_id must be TenantId"
            )

        if (
            account_id is not None
            and not isinstance(
                account_id,
                BrokerAccountId,
            )
        ):
            raise TypeError(
                "account_id must be BrokerAccountId or None"
            )

        if principal.tenant_id != tenant_id:
            return AccessDecision(
                allowed=False,
                reason=(
                    AccessDeniedReason
                    .TENANT_MISMATCH
                ),
            )

        permissions = _ROLE_PERMISSIONS.get(
            principal.role,
            frozenset(),
        )

        if permission not in permissions:
            return AccessDecision(
                allowed=False,
                reason=(
                    AccessDeniedReason
                    .PERMISSION_DENIED
                ),
            )

        if (
            permission
            in _ACCOUNT_SCOPED_PERMISSIONS
        ):
            if account_id is None:
                return AccessDecision(
                    allowed=False,
                    reason=(
                        AccessDeniedReason
                        .ACCOUNT_REQUIRED
                    ),
                )

            if (
                principal.role is UserRole.USER
                and not principal.has_account(
                    account_id
                )
            ):
                return AccessDecision(
                    allowed=False,
                    reason=(
                        AccessDeniedReason
                        .ACCOUNT_SCOPE_MISMATCH
                    ),
                )

        return AccessDecision(
            allowed=True
        )

    def require(
        self,
        *,
        principal: AuthenticatedPrincipal,
        permission: AccessPermission,
        tenant_id: TenantId,
        account_id: BrokerAccountId | None = None,
    ) -> None:
        decision = self.evaluate(
            principal=principal,
            permission=permission,
            tenant_id=tenant_id,
            account_id=account_id,
        )

        if decision.allowed:
            return

        reason = decision.reason

        if reason is None:
            raise RuntimeError(
                "denied access decision has no reason"
            )

        raise AccessDeniedError(
            reason=reason
        )


__all__ = [
    "AccessDecision",
    "AccessDeniedError",
    "AccessDeniedReason",
    "AccessPermission",
    "AuthenticatedPrincipal",
    "RbacPolicy",
    "TenantId",
    "UserId",
    "UserRole",
]
