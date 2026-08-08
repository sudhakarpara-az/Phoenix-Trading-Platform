"""
Phoenix M09 Broker / Account Reconciliation.

Responsibilities:
    - restore M09 account state during startup/recovery
    - compare persisted account identity with configured account
    - refresh live session/profile/funds/connectivity
    - rebuild AccountStateRegistry from current broker truth
    - detect unsafe reconciliation mismatches
    - fail closed when account truth cannot be established

This module does NOT:
    - reconcile orders or positions
    - place BUY/SELL orders
    - own M08 runtime transitions
    - store credentials
    - call Dhan directly

M08 continues to own trading/order/position recovery.
M09 owns broker-account readiness recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

from src.account.account_runtime_service import (
    AccountRuntimeRefreshResult,
    AccountRuntimeService,
)
from src.account.account_state_registry import (
    AccountStateRegistry,
)
from src.account.account_types import (
    AccountEligibilityReason,
    AccountHealthStatus,
    BrokerAccountId,
    BrokerType,
)
from src.account.session_reauth_service import (
    SessionReauthService,
)


class AccountReconciliationIssueCode(
    str,
    Enum,
):
    ACCOUNT_NOT_PERSISTED = (
        "ACCOUNT_NOT_PERSISTED"
    )

    ACCOUNT_ID_MISMATCH = (
        "ACCOUNT_ID_MISMATCH"
    )

    BROKER_MISMATCH = (
        "BROKER_MISMATCH"
    )

    SESSION_RECOVERY_FAILED = (
        "SESSION_RECOVERY_FAILED"
    )

    BROKER_UNAVAILABLE = (
        "BROKER_UNAVAILABLE"
    )

    PROFILE_UNAVAILABLE = (
        "PROFILE_UNAVAILABLE"
    )

    FUNDS_UNAVAILABLE = (
        "FUNDS_UNAVAILABLE"
    )

    ACCOUNT_BLOCKED = (
        "ACCOUNT_BLOCKED"
    )

    ACCOUNT_INACTIVE = (
        "ACCOUNT_INACTIVE"
    )

    TRADING_NOT_ENABLED = (
        "TRADING_NOT_ENABLED"
    )

    RECONCILIATION_FAILED = (
        "RECONCILIATION_FAILED"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class PersistedBrokerAccountState:
    broker: BrokerType

    account_id: BrokerAccountId


class PersistedAccountStateProvider(
    Protocol,
):
    """
    Persistence-facing account recovery boundary.

    T15 deliberately avoids importing SQLAlchemy repositories
    directly into reconciliation logic.
    """

    def load_account(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
    ) -> PersistedBrokerAccountState | None:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class AccountReconciliationIssue:
    code: AccountReconciliationIssueCode

    message: str


@dataclass(
    frozen=True,
    slots=True,
)
class AccountReconciliationResult:
    broker: BrokerType

    account_id: BrokerAccountId

    completed: bool

    reconciled_at: datetime

    refresh_result: (
        AccountRuntimeRefreshResult
        | None
    )

    issues: tuple[
        AccountReconciliationIssue,
        ...
    ]

    @property
    def new_entries_allowed(
        self,
    ) -> bool:
        return (
            self.completed
            and self.refresh_result is not None
            and self.refresh_result
            .new_entries_allowed
        )


class AccountReconciliationService:
    """
    Reconciles persisted M09 account state against live broker
    state and restores AccountStateRegistry.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        persisted_state:
            PersistedAccountStateProvider,
        session_reauth:
            SessionReauthService,
        account_runtime:
            AccountRuntimeService,
        state_registry:
            AccountStateRegistry,
    ) -> None:
        self._broker = broker
        self._account_id = account_id
        self._persisted_state = (
            persisted_state
        )
        self._session_reauth = (
            session_reauth
        )
        self._account_runtime = (
            account_runtime
        )
        self._state_registry = (
            state_registry
        )

        self._validate_identity()

    @property
    def broker(
        self,
    ) -> BrokerType:
        return self._broker

    @property
    def account_id(
        self,
    ) -> BrokerAccountId:
        return self._account_id

    def reconcile(
        self,
        *,
        required_cash: Decimal,
        reconciled_at: datetime,
    ) -> AccountReconciliationResult:
        if required_cash < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        persisted = (
            self._persisted_state
            .load_account(
                broker=self._broker,
                account_id=self._account_id,
            )
        )

        issues: list[
            AccountReconciliationIssue
        ] = []

        if persisted is None:
            issues.append(
                AccountReconciliationIssue(
                    code=(
                        AccountReconciliationIssueCode
                        .ACCOUNT_NOT_PERSISTED
                    ),
                    message=(
                        "persisted broker account "
                        "state not found"
                    ),
                )
            )

            return (
                AccountReconciliationResult(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    completed=False,
                    reconciled_at=(
                        reconciled_at
                    ),
                    refresh_result=None,
                    issues=tuple(issues),
                )
            )

        if (
            persisted.broker
            is not self._broker
        ):
            issues.append(
                AccountReconciliationIssue(
                    code=(
                        AccountReconciliationIssueCode
                        .BROKER_MISMATCH
                    ),
                    message=(
                        "persisted broker does not "
                        "match configured broker"
                    ),
                )
            )

        if (
            persisted.account_id
            != self._account_id
        ):
            issues.append(
                AccountReconciliationIssue(
                    code=(
                        AccountReconciliationIssueCode
                        .ACCOUNT_ID_MISMATCH
                    ),
                    message=(
                        "persisted account does not "
                        "match configured account"
                    ),
                )
            )

        if issues:
            return (
                AccountReconciliationResult(
                    broker=self._broker,
                    account_id=self._account_id,
                    completed=False,
                    reconciled_at=reconciled_at,
                    refresh_result=None,
                    issues=tuple(issues),
                )
            )

        # ----------------------------------------------------
        # Restore / validate broker session
        # ----------------------------------------------------

        reauth = (
            self._session_reauth
            .ensure_authenticated(
                checked_at=reconciled_at
            )
        )

        if not reauth.authenticated:
            issues.append(
                AccountReconciliationIssue(
                    code=(
                        AccountReconciliationIssueCode
                        .SESSION_RECOVERY_FAILED
                    ),
                    message=(
                        reauth.message
                        or (
                            "broker session could "
                            "not be authenticated"
                        )
                    ),
                )
            )

            return (
                AccountReconciliationResult(
                    broker=self._broker,
                    account_id=self._account_id,
                    completed=False,
                    reconciled_at=reconciled_at,
                    refresh_result=None,
                    issues=tuple(issues),
                )
            )

        # ----------------------------------------------------
        # Refresh live broker/account truth
        # ----------------------------------------------------

        try:
            refresh = (
                self._account_runtime
                .refresh(
                    required_cash=(
                        required_cash
                    ),
                    refreshed_at=(
                        reconciled_at
                    ),
                )
            )

        except Exception as exc:
            issues.append(
                AccountReconciliationIssue(
                    code=(
                        AccountReconciliationIssueCode
                        .RECONCILIATION_FAILED
                    ),
                    message=str(exc),
                )
            )

            return (
                AccountReconciliationResult(
                    broker=self._broker,
                    account_id=self._account_id,
                    completed=False,
                    reconciled_at=reconciled_at,
                    refresh_result=None,
                    issues=tuple(issues),
                )
            )

        # ----------------------------------------------------
        # Fail closed on unresolved account dependencies
        # ----------------------------------------------------

        if (
            refresh.health.status
            is AccountHealthStatus.UNHEALTHY
        ):
            issues.append(
                AccountReconciliationIssue(
                    code=(
                        AccountReconciliationIssueCode
                        .BROKER_UNAVAILABLE
                    ),
                    message=(
                        refresh.health.message
                        or (
                            "account health "
                            "is unhealthy"
                        )
                    ),
                )
            )

        elif (
            refresh.health.status
            is AccountHealthStatus.DEGRADED
        ):
            if (
                not refresh.health.profile_available
            ):
                issues.append(
                    AccountReconciliationIssue(
                        code=(
                            AccountReconciliationIssueCode
                            .PROFILE_UNAVAILABLE
                        ),
                        message=(
                            "current broker profile "
                            "could not be verified"
                        ),
                    )
                )

            if (
                not refresh.health.funds_available
            ):
                issues.append(
                    AccountReconciliationIssue(
                        code=(
                            AccountReconciliationIssueCode
                            .FUNDS_UNAVAILABLE
                        ),
                        message=(
                            "current broker funds "
                            "could not be verified"
                        ),
                    )
                )

        # Eligibility may also reveal non-health account blocks.
        reason = (
            refresh.eligibility.reason
        )

        if not refresh.eligibility.allowed:
            if (
                reason
                is AccountEligibilityReason
                .ACCOUNT_BLOCKED
            ):
                issues.append(
                    AccountReconciliationIssue(
                        code=(
                            AccountReconciliationIssueCode
                            .ACCOUNT_BLOCKED
                        ),
                        message=(
                            "broker account is blocked"
                        ),
                    )
                )

            elif (
                reason
                is AccountEligibilityReason
                .ACCOUNT_INACTIVE
            ):
                issues.append(
                    AccountReconciliationIssue(
                        code=(
                            AccountReconciliationIssueCode
                            .ACCOUNT_INACTIVE
                        ),
                        message=(
                            "broker account is inactive"
                        ),
                    )
                )

            elif (
                reason
                is AccountEligibilityReason
                .TRADING_NOT_ENABLED
            ):
                issues.append(
                    AccountReconciliationIssue(
                        code=(
                            AccountReconciliationIssueCode
                            .TRADING_NOT_ENABLED
                        ),
                        message=(
                            "trading is not enabled "
                            "for broker account"
                        ),
                    )
                )

            elif (
                reason
                is AccountEligibilityReason
                .BROKER_UNAVAILABLE
                and not any(
                    issue.code
                    is AccountReconciliationIssueCode
                    .BROKER_UNAVAILABLE
                    for issue in issues
                )
            ):
                issues.append(
                    AccountReconciliationIssue(
                        code=(
                            AccountReconciliationIssueCode
                            .BROKER_UNAVAILABLE
                        ),
                        message=(
                            "broker account "
                            "unavailable"
                        ),
                    )
                )

            elif (
                reason
                is AccountEligibilityReason
                .PROFILE_UNAVAILABLE
                and not any(
                    issue.code
                    is AccountReconciliationIssueCode
                    .PROFILE_UNAVAILABLE
                    for issue in issues
                )
            ):
                issues.append(
                    AccountReconciliationIssue(
                        code=(
                            AccountReconciliationIssueCode
                            .PROFILE_UNAVAILABLE
                        ),
                        message=(
                            "account profile unavailable"
                        ),
                    )
                )

            elif (
                reason
                is AccountEligibilityReason
                .FUNDS_UNAVAILABLE
                and not any(
                    issue.code
                    is AccountReconciliationIssueCode
                    .FUNDS_UNAVAILABLE
                    for issue in issues
                )
            ):
                issues.append(
                    AccountReconciliationIssue(
                        code=(
                            AccountReconciliationIssueCode
                            .FUNDS_UNAVAILABLE
                        ),
                        message=(
                            "account funds unavailable"
                        ),
                    )
                )

        # Insufficient funds is intentionally NOT a recovery
        # failure. Broker/account truth is valid; it simply
        # blocks the new entry being evaluated.
        fatal_issues = tuple(
            issue
            for issue in issues
            if issue.code
            not in {
                # intentionally none yet; kept explicit
            }
        )

        completed = (
            len(fatal_issues)
            == 0
        )

        return AccountReconciliationResult(
            broker=self._broker,
            account_id=self._account_id,
            completed=completed,
            reconciled_at=reconciled_at,
            refresh_result=refresh,
            issues=fatal_issues,
        )

    def _validate_identity(
        self,
    ) -> None:
        components = (
            self._session_reauth,
            self._account_runtime,
        )

        for component in components:
            if (
                component.broker
                is not self._broker
            ):
                raise ValueError(
                    "account reconciliation "
                    "broker mismatch"
                )

            if (
                component.account_id
                != self._account_id
            ):
                raise ValueError(
                    "account reconciliation "
                    "account mismatch"
                )