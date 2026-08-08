"""
Phoenix M09 Broker & Account domain models.

Defines application-level broker/account identity, session,
profile, funds, health and trading-eligibility state.

This module contains no:
    - Dhan API calls
    - database access
    - order execution
    - strategy logic
    - position/risk calculations
    - authentication implementation

Those responsibilities belong to later M09 tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


# ============================================================
# Broker identity
# ============================================================


class BrokerType(
    str,
    Enum,
):
    """
    Broker identity supported by Phoenix.

    M09 begins with Dhan, while keeping broker identity explicit
    so account-domain code does not depend on Dhan-specific
    constants.
    """

    DHAN = "DHAN"


@dataclass(
    frozen=True,
    slots=True,
)
class BrokerAccountId:
    """
    Stable Phoenix identity for one broker trading account.

    This is intentionally separate from broker credentials.
    """

    value: str

    def __post_init__(
        self,
    ) -> None:
        normalized = self.value.strip()

        if not normalized:
            raise ValueError(
                "broker account id cannot be empty"
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


class BrokerAccountStatus(
    str,
    Enum,
):
    """
    Broker-reported/account-management status.

    UNKNOWN:
        Account status has not yet been confirmed.

    ACTIVE:
        Account is active at the broker.

    INACTIVE:
        Account exists but is not currently trading-enabled.

    BLOCKED:
        Account must not accept new trading activity.
    """

    UNKNOWN = "UNKNOWN"

    ACTIVE = "ACTIVE"

    INACTIVE = "INACTIVE"

    BLOCKED = "BLOCKED"


# ============================================================
# Broker session
# ============================================================


class BrokerSessionStatus(
    str,
    Enum,
):
    """
    Authentication/session lifecycle.
    """

    NOT_INITIALIZED = "NOT_INITIALIZED"

    AUTHENTICATING = "AUTHENTICATING"

    AUTHENTICATED = "AUTHENTICATED"

    EXPIRED = "EXPIRED"

    FAILED = "FAILED"

    CLOSED = "CLOSED"


@dataclass(
    frozen=True,
    slots=True,
)
class BrokerSessionSnapshot:
    """
    Point-in-time broker session state.

    Secrets and access tokens must never be stored here.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    status: BrokerSessionStatus

    updated_at: datetime

    authenticated_at: datetime | None = None

    expires_at: datetime | None = None

    failure_message: str | None = None

    def __post_init__(
        self,
    ) -> None:
        if (
            self.authenticated_at is not None
            and self.authenticated_at
            > self.updated_at
        ):
            raise ValueError(
                "authenticated_at cannot be "
                "after updated_at"
            )

        if (
            self.expires_at is not None
            and self.authenticated_at is None
        ):
            raise ValueError(
                "session expires_at requires "
                "authenticated_at"
            )

        if (
            self.expires_at is not None
            and self.authenticated_at is not None
            and self.expires_at
            <= self.authenticated_at
        ):
            raise ValueError(
                "session expires_at must be "
                "after authenticated_at"
            )

        if (
            self.status
            is BrokerSessionStatus.AUTHENTICATED
            and self.authenticated_at is None
        ):
            raise ValueError(
                "AUTHENTICATED session requires "
                "authenticated_at"
            )

        if (
            self.status
            is BrokerSessionStatus.FAILED
            and self.failure_message is None
        ):
            raise ValueError(
                "FAILED session requires "
                "failure_message"
            )

        if (
            self.status
            is not BrokerSessionStatus.FAILED
            and self.failure_message is not None
        ):
            raise ValueError(
                "failure_message is only valid "
                "for FAILED session"
            )

        if self.failure_message is not None:
            message = self.failure_message.strip()

            if not message:
                raise ValueError(
                    "session failure message "
                    "cannot be empty"
                )

            if message != self.failure_message:
                object.__setattr__(
                    self,
                    "failure_message",
                    message,
                )

    @property
    def authenticated(
        self,
    ) -> bool:
        return (
            self.status
            is BrokerSessionStatus.AUTHENTICATED
        )

    @property
    def usable_for_new_entries(
        self,
    ) -> bool:
        """
        Session-level gate only.

        Account, funds, runtime and risk gates are evaluated
        separately.
        """

        return self.authenticated


# ============================================================
# Account profile
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class AccountProfile:
    """
    Broker account identity/profile.

    Contains no credentials or authentication tokens.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    account_status: BrokerAccountStatus

    fetched_at: datetime

    client_name: str | None = None

    trading_enabled: bool = False

    product_type: str | None = None

    def __post_init__(
        self,
    ) -> None:
        if self.client_name is not None:
            name = self.client_name.strip()

            if not name:
                raise ValueError(
                    "client name cannot be empty"
                )

            if name != self.client_name:
                object.__setattr__(
                    self,
                    "client_name",
                    name,
                )

        if self.product_type is not None:
            product_type = (
                self.product_type.strip()
            )

            if not product_type:
                raise ValueError(
                    "product type cannot be empty"
                )

            if (
                product_type
                != self.product_type
            ):
                object.__setattr__(
                    self,
                    "product_type",
                    product_type,
                )

    @property
    def active(
        self,
    ) -> bool:
        return (
            self.account_status
            is BrokerAccountStatus.ACTIVE
        )

    @property
    def eligible_account_state(
        self,
    ) -> bool:
        return (
            self.active
            and self.trading_enabled
        )


# ============================================================
# Funds / margin
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class AccountFundsSnapshot:
    """
    Point-in-time account funds and margin state.

    Decimal is used intentionally for monetary values.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    available_cash: Decimal

    available_margin: Decimal

    utilized_margin: Decimal

    fetched_at: datetime

    collateral: Decimal = Decimal("0")

    opening_balance: Decimal | None = None

    def __post_init__(
        self,
    ) -> None:
        monetary_values = {
            "available_cash":
                self.available_cash,

            "available_margin":
                self.available_margin,

            "utilized_margin":
                self.utilized_margin,

            "collateral":
                self.collateral,
        }

        for (
            name,
            value,
        ) in monetary_values.items():
            if value < Decimal("0"):
                raise ValueError(
                    f"{name} cannot be negative"
                )

        if (
            self.opening_balance is not None
            and self.opening_balance
            < Decimal("0")
        ):
            raise ValueError(
                "opening_balance cannot be negative"
            )

    @property
    def total_available(
        self,
    ) -> Decimal:
        """
        Informational aggregate only.

        Actual broker margin eligibility remains broker-defined.
        """

        return (
            self.available_cash
            + self.available_margin
        )

    def has_available_cash(
        self,
        required: Decimal,
    ) -> bool:
        if required < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        return (
            self.available_cash
            >= required
        )


# ============================================================
# Account health
# ============================================================


class AccountHealthStatus(
    str,
    Enum,
):
    UNKNOWN = "UNKNOWN"

    HEALTHY = "HEALTHY"

    DEGRADED = "DEGRADED"

    UNHEALTHY = "UNHEALTHY"


@dataclass(
    frozen=True,
    slots=True,
)
class AccountHealthSnapshot:
    """
    Aggregate account/broker health state.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    status: AccountHealthStatus

    checked_at: datetime

    broker_connected: bool

    session_authenticated: bool

    profile_available: bool

    funds_available: bool

    message: str | None = None

    def __post_init__(
        self,
    ) -> None:
        if self.message is not None:
            message = self.message.strip()

            if not message:
                raise ValueError(
                    "account health message "
                    "cannot be empty"
                )

            if message != self.message:
                object.__setattr__(
                    self,
                    "message",
                    message,
                )

    @property
    def healthy(
        self,
    ) -> bool:
        return (
            self.status
            is AccountHealthStatus.HEALTHY
        )

    @property
    def new_entry_dependencies_ready(
        self,
    ) -> bool:
        return (
            self.healthy
            and self.broker_connected
            and self.session_authenticated
            and self.profile_available
            and self.funds_available
        )


# ============================================================
# Account trading eligibility
# ============================================================


class AccountEligibilityStatus(
    str,
    Enum,
):
    ALLOWED = "ALLOWED"

    BLOCKED = "BLOCKED"


class AccountEligibilityReason(
    str,
    Enum,
):
    """
    M09-owned account/broker eligibility reasons.

    Runtime/risk reasons deliberately remain in M08/M07.
    """

    ELIGIBLE = "ELIGIBLE"

    ACCOUNT_STATUS_UNKNOWN = (
        "ACCOUNT_STATUS_UNKNOWN"
    )

    ACCOUNT_INACTIVE = (
        "ACCOUNT_INACTIVE"
    )

    ACCOUNT_BLOCKED = (
        "ACCOUNT_BLOCKED"
    )

    TRADING_NOT_ENABLED = (
        "TRADING_NOT_ENABLED"
    )

    SESSION_NOT_AUTHENTICATED = (
        "SESSION_NOT_AUTHENTICATED"
    )

    SESSION_EXPIRED = (
        "SESSION_EXPIRED"
    )

    SESSION_FAILED = (
        "SESSION_FAILED"
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

    INSUFFICIENT_FUNDS = (
        "INSUFFICIENT_FUNDS"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class AccountTradingEligibility:
    """
    Final account-level new-entry decision.

    This is NOT the complete Phoenix order eligibility result.

    M07 risk, M08 runtime and M06 execution gates remain
    independent.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    status: AccountEligibilityStatus

    reason: AccountEligibilityReason

    evaluated_at: datetime

    message: str | None = None

    available_cash: Decimal | None = None

    required_cash: Decimal | None = None

    def __post_init__(
        self,
    ) -> None:
        if (
            self.status
            is AccountEligibilityStatus.ALLOWED
            and self.reason
            is not AccountEligibilityReason.ELIGIBLE
        ):
            raise ValueError(
                "ALLOWED eligibility requires "
                "ELIGIBLE reason"
            )

        if (
            self.status
            is AccountEligibilityStatus.BLOCKED
            and self.reason
            is AccountEligibilityReason.ELIGIBLE
        ):
            raise ValueError(
                "BLOCKED eligibility cannot use "
                "ELIGIBLE reason"
            )

        if (
            self.available_cash is not None
            and self.available_cash
            < Decimal("0")
        ):
            raise ValueError(
                "available_cash cannot be negative"
            )

        if (
            self.required_cash is not None
            and self.required_cash
            < Decimal("0")
        ):
            raise ValueError(
                "required_cash cannot be negative"
            )

        if self.message is not None:
            message = self.message.strip()

            if not message:
                raise ValueError(
                    "eligibility message cannot be empty"
                )

            if message != self.message:
                object.__setattr__(
                    self,
                    "message",
                    message,
                )

    @property
    def allowed(
        self,
    ) -> bool:
        return (
            self.status
            is AccountEligibilityStatus.ALLOWED
        )

    @classmethod
    def allow(
        cls,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        evaluated_at: datetime,
        available_cash: Decimal | None = None,
        required_cash: Decimal | None = None,
    ) -> "AccountTradingEligibility":
        return cls(
            broker=broker,
            account_id=account_id,
            status=(
                AccountEligibilityStatus
                .ALLOWED
            ),
            reason=(
                AccountEligibilityReason
                .ELIGIBLE
            ),
            evaluated_at=evaluated_at,
            available_cash=available_cash,
            required_cash=required_cash,
        )

    @classmethod
    def block(
        cls,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        reason: AccountEligibilityReason,
        evaluated_at: datetime,
        message: str | None = None,
        available_cash: Decimal | None = None,
        required_cash: Decimal | None = None,
    ) -> "AccountTradingEligibility":
        if (
            reason
            is AccountEligibilityReason.ELIGIBLE
        ):
            raise ValueError(
                "blocked eligibility requires "
                "a blocking reason"
            )

        return cls(
            broker=broker,
            account_id=account_id,
            status=(
                AccountEligibilityStatus
                .BLOCKED
            ),
            reason=reason,
            evaluated_at=evaluated_at,
            message=message,
            available_cash=available_cash,
            required_cash=required_cash,
        )