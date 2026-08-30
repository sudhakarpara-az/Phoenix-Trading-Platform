"""
M15 identity, RBAC, and tenant-isolation tests.
"""

from __future__ import annotations

import pytest

from typing import Callable

from src.account.account_types import (
    BrokerAccountId,
)
from src.api.access_control import (
    AccessDeniedError,
    AccessDeniedReason,
    AccessPermission,
    AuthenticatedPrincipal,
    RbacPolicy,
    TenantId,
    UserId,
    UserRole,
)


def _user_principal(
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=UserId("USER-001"),
        tenant_id=TenantId("TENANT-A"),
        role=UserRole.USER,
        account_ids=(
            BrokerAccountId("DHAN-A"),
        ),
    )


def _admin_principal(
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=UserId("ADMIN-001"),
        tenant_id=TenantId("TENANT-A"),
        role=UserRole.ADMIN,
    )


def test_identity_values_are_normalized(
) -> None:
    tenant_id = TenantId(
        "  TENANT-A  "
    )
    user_id = UserId(
        "  USER-001  "
    )

    assert tenant_id.value == "TENANT-A"
    assert user_id.value == "USER-001"
    assert str(tenant_id) == "TENANT-A"
    assert str(user_id) == "USER-001"


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: TenantId("  "),
            "tenant id cannot be empty",
        ),
        (
            lambda: UserId(""),
            "user id cannot be empty",
        ),
    ],
)
def test_empty_identity_is_rejected(
    factory: Callable[[], object],
    message: str,
) -> None:
    with pytest.raises(
        ValueError,
        match=message,
    ):
        factory()


def test_principal_rejects_duplicate_account_scope(
) -> None:
    account_id = BrokerAccountId(
        "DHAN-A"
    )

    with pytest.raises(
        ValueError,
        match=(
            "account_ids cannot "
            "contain duplicates"
        ),
    ):
        AuthenticatedPrincipal(
            user_id=UserId("USER-001"),
            tenant_id=TenantId("TENANT-A"),
            role=UserRole.USER,
            account_ids=(
                account_id,
                account_id,
            ),
        )


@pytest.mark.parametrize(
    "permission",
    [
        AccessPermission.READ_OPERATOR_DATA,
        AccessPermission.READ_REPORTS,
        AccessPermission.CONTROL_TRADING,
    ],
)
def test_user_can_use_granted_permission_for_owned_account(
    permission: AccessPermission,
) -> None:
    principal = _user_principal()

    decision = RbacPolicy().evaluate(
        principal=principal,
        permission=permission,
        tenant_id=TenantId("TENANT-A"),
        account_id=BrokerAccountId("DHAN-A"),
    )

    assert decision.allowed
    assert decision.reason is None


def test_user_is_denied_for_unowned_account(
) -> None:
    decision = RbacPolicy().evaluate(
        principal=_user_principal(),
        permission=(
            AccessPermission
            .READ_OPERATOR_DATA
        ),
        tenant_id=TenantId("TENANT-A"),
        account_id=BrokerAccountId("DHAN-B"),
    )

    assert not decision.allowed
    assert (
        decision.reason
        is AccessDeniedReason.ACCOUNT_SCOPE_MISMATCH
    )


def test_account_scoped_permission_requires_account(
) -> None:
    decision = RbacPolicy().evaluate(
        principal=_user_principal(),
        permission=(
            AccessPermission
            .CONTROL_TRADING
        ),
        tenant_id=TenantId("TENANT-A"),
    )

    assert not decision.allowed
    assert (
        decision.reason
        is AccessDeniedReason.ACCOUNT_REQUIRED
    )


def test_user_cannot_manage_users(
) -> None:
    decision = RbacPolicy().evaluate(
        principal=_user_principal(),
        permission=(
            AccessPermission
            .MANAGE_USERS
        ),
        tenant_id=TenantId("TENANT-A"),
    )

    assert not decision.allowed
    assert (
        decision.reason
        is AccessDeniedReason.PERMISSION_DENIED
    )


def test_admin_can_manage_own_tenant(
) -> None:
    decision = RbacPolicy().evaluate(
        principal=_admin_principal(),
        permission=(
            AccessPermission
            .MANAGE_TENANT
        ),
        tenant_id=TenantId("TENANT-A"),
    )

    assert decision.allowed
    assert decision.reason is None


def test_admin_can_access_resolved_account_in_own_tenant(
) -> None:
    decision = RbacPolicy().evaluate(
        principal=_admin_principal(),
        permission=(
            AccessPermission
            .READ_OPERATOR_DATA
        ),
        tenant_id=TenantId("TENANT-A"),
        account_id=BrokerAccountId("DHAN-B"),
    )

    assert decision.allowed
    assert decision.reason is None


@pytest.mark.parametrize(
    "role",
    [
        UserRole.ADMIN,
        UserRole.USER,
    ],
)
def test_every_role_is_denied_across_tenant_boundary(
    role: UserRole,
) -> None:
    principal = AuthenticatedPrincipal(
        user_id=UserId("USER-001"),
        tenant_id=TenantId("TENANT-A"),
        role=role,
        account_ids=(
            BrokerAccountId("DHAN-A"),
        ),
    )

    decision = RbacPolicy().evaluate(
        principal=principal,
        permission=(
            AccessPermission
            .READ_OPERATOR_DATA
        ),
        tenant_id=TenantId("TENANT-B"),
        account_id=BrokerAccountId("DHAN-A"),
    )

    assert not decision.allowed
    assert (
        decision.reason
        is AccessDeniedReason.TENANT_MISMATCH
    )


def test_require_raises_generic_access_denied_error(
) -> None:
    with pytest.raises(
        AccessDeniedError,
        match="^access denied$",
    ) as raised:
        RbacPolicy().require(
            principal=_user_principal(),
            permission=(
                AccessPermission
                .MANAGE_USERS
            ),
            tenant_id=TenantId("TENANT-A"),
        )

    assert (
        raised.value.reason
        is AccessDeniedReason.PERMISSION_DENIED
    )
