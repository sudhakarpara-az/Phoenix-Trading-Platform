"""
Phoenix M09-T01 Broker & Account Domain Model tests.
"""

from datetime import (
    datetime,
    timedelta,
)
from decimal import Decimal

import pytest

from src.account.account_types import (
    AccountEligibilityReason,
    AccountEligibilityStatus,
    AccountFundsSnapshot,
    AccountHealthSnapshot,
    AccountHealthStatus,
    AccountProfile,
    AccountTradingEligibility,
    BrokerAccountId,
    BrokerAccountStatus,
    BrokerSessionSnapshot,
    BrokerSessionStatus,
    BrokerType,
)


NOW = datetime(
    2026,
    8,
    8,
    10,
    0,
)

LATER = (
    NOW
    + timedelta(hours=1)
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-ACCOUNT-001"
)


# ============================================================
# Broker identity
# ============================================================


def test_broker_type_dhan() -> None:
    assert (
        BrokerType.DHAN.value
        == "DHAN"
    )


def test_broker_account_id() -> None:
    account_id = BrokerAccountId(
        "DHAN-001"
    )

    assert (
        account_id.value
        == "DHAN-001"
    )

    assert (
        str(account_id)
        == "DHAN-001"
    )


def test_broker_account_id_trimmed() -> None:
    account_id = BrokerAccountId(
        "  DHAN-001  "
    )

    assert (
        account_id.value
        == "DHAN-001"
    )


def test_empty_broker_account_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "broker account id cannot be empty"
        ),
    ):
        BrokerAccountId(" ")


# ============================================================
# Session
# ============================================================


def test_authenticated_session() -> None:
    snapshot = BrokerSessionSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=(
            BrokerSessionStatus
            .AUTHENTICATED
        ),
        authenticated_at=NOW,
        updated_at=NOW,
        expires_at=LATER,
    )

    assert snapshot.authenticated is True

    assert (
        snapshot.usable_for_new_entries
        is True
    )


def test_authenticated_session_requires_time() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "AUTHENTICATED session requires "
            "authenticated_at"
        ),
    ):
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            updated_at=NOW,
        )


def test_session_expiry_requires_auth_time() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "session expires_at requires "
            "authenticated_at"
        ),
    ):
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus.EXPIRED
            ),
            updated_at=NOW,
            expires_at=LATER,
        )


def test_session_expiry_must_follow_authentication() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "session expires_at must be "
            "after authenticated_at"
        ),
    ):
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            updated_at=NOW,
            authenticated_at=NOW,
            expires_at=NOW,
        )


def test_authentication_time_cannot_be_future() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "authenticated_at cannot be "
            "after updated_at"
        ),
    ):
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            authenticated_at=LATER,
            updated_at=NOW,
        )


def test_failed_session_requires_failure_message() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "FAILED session requires "
            "failure_message"
        ),
    ):
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus.FAILED
            ),
            updated_at=NOW,
        )


def test_failed_session() -> None:
    snapshot = BrokerSessionSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=BrokerSessionStatus.FAILED,
        updated_at=NOW,
        failure_message=(
            "authentication failed"
        ),
    )

    assert snapshot.authenticated is False

    assert (
        snapshot.usable_for_new_entries
        is False
    )


def test_failure_message_not_allowed_on_good_session() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "failure_message is only valid "
            "for FAILED session"
        ),
    ):
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus
                .NOT_INITIALIZED
            ),
            updated_at=NOW,
            failure_message="error",
        )


def test_expired_session_blocks_entries() -> None:
    snapshot = BrokerSessionSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=(
            BrokerSessionStatus.EXPIRED
        ),
        authenticated_at=NOW,
        expires_at=LATER,
        updated_at=LATER,
    )

    assert snapshot.authenticated is False

    assert (
        snapshot.usable_for_new_entries
        is False
    )


# ============================================================
# Profile
# ============================================================


def test_active_account_profile() -> None:
    profile = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.ACTIVE
        ),
        fetched_at=NOW,
        client_name="Phoenix Trader",
        trading_enabled=True,
        product_type="OPTIONS",
    )

    assert profile.active is True

    assert (
        profile.eligible_account_state
        is True
    )


def test_active_but_trading_disabled_profile_not_eligible() -> None:
    profile = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.ACTIVE
        ),
        fetched_at=NOW,
        trading_enabled=False,
    )

    assert profile.active is True

    assert (
        profile.eligible_account_state
        is False
    )


def test_blocked_account_not_active() -> None:
    profile = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.BLOCKED
        ),
        fetched_at=NOW,
        trading_enabled=True,
    )

    assert profile.active is False

    assert (
        profile.eligible_account_state
        is False
    )


def test_profile_text_is_trimmed() -> None:
    profile = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.ACTIVE
        ),
        fetched_at=NOW,
        client_name="  Phoenix  ",
        product_type="  OPTIONS  ",
        trading_enabled=True,
    )

    assert (
        profile.client_name
        == "Phoenix"
    )

    assert (
        profile.product_type
        == "OPTIONS"
    )


# ============================================================
# Funds
# ============================================================


def test_account_funds_snapshot() -> None:
    funds = AccountFundsSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        available_cash=Decimal(
            "100000.00"
        ),
        available_margin=Decimal(
            "25000.00"
        ),
        utilized_margin=Decimal(
            "15000.00"
        ),
        collateral=Decimal(
            "5000.00"
        ),
        opening_balance=Decimal(
            "110000.00"
        ),
        fetched_at=NOW,
    )

    assert (
        funds.available_cash
        == Decimal("100000.00")
    )


def test_total_available_funds() -> None:
    funds = AccountFundsSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        available_cash=Decimal(
            "100000"
        ),
        available_margin=Decimal(
            "25000"
        ),
        utilized_margin=Decimal(
            "10000"
        ),
        fetched_at=NOW,
    )

    assert (
        funds.total_available
        == Decimal("125000")
    )


def test_has_available_cash() -> None:
    funds = AccountFundsSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        available_cash=Decimal(
            "100000"
        ),
        available_margin=Decimal(
            "0"
        ),
        utilized_margin=Decimal(
            "0"
        ),
        fetched_at=NOW,
    )

    assert (
        funds.has_available_cash(
            Decimal("99999")
        )
        is True
    )

    assert (
        funds.has_available_cash(
            Decimal("100000")
        )
        is True
    )

    assert (
        funds.has_available_cash(
            Decimal("100001")
        )
        is False
    )


@pytest.mark.parametrize(
    "field,value",
    [
        (
            "available_cash",
            Decimal("-1"),
        ),
        (
            "available_margin",
            Decimal("-1"),
        ),
        (
            "utilized_margin",
            Decimal("-1"),
        ),
        (
            "collateral",
            Decimal("-1"),
        ),
    ],
)
def test_negative_funds_rejected(
    field,
    value,
) -> None:
    values = {
        "available_cash":
            Decimal("0"),

        "available_margin":
            Decimal("0"),

        "utilized_margin":
            Decimal("0"),

        "collateral":
            Decimal("0"),
    }

    values[field] = value

    with pytest.raises(
        ValueError,
        match=(
            f"{field} cannot be negative"
        ),
    ):
        AccountFundsSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            available_cash=(
                values[
                    "available_cash"
                ]
            ),
            available_margin=(
                values[
                    "available_margin"
                ]
            ),
            utilized_margin=(
                values[
                    "utilized_margin"
                ]
            ),
            collateral=(
                values[
                    "collateral"
                ]
            ),
            fetched_at=NOW,
        )


def test_negative_required_cash_rejected() -> None:
    funds = AccountFundsSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        available_cash=Decimal("100"),
        available_margin=Decimal("0"),
        utilized_margin=Decimal("0"),
        fetched_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "required cash cannot be negative"
        ),
    ):
        funds.has_available_cash(
            Decimal("-1")
        )


# ============================================================
# Account Health
# ============================================================


def test_healthy_account_health_snapshot() -> None:
    health = AccountHealthSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=(
            AccountHealthStatus.HEALTHY
        ),
        checked_at=NOW,
        broker_connected=True,
        session_authenticated=True,
        profile_available=True,
        funds_available=True,
    )

    assert health.healthy is True

    assert (
        health.new_entry_dependencies_ready
        is True
    )


def test_degraded_health_blocks_dependency_readiness() -> None:
    health = AccountHealthSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=(
            AccountHealthStatus.DEGRADED
        ),
        checked_at=NOW,
        broker_connected=True,
        session_authenticated=True,
        profile_available=True,
        funds_available=True,
        message="funds data delayed",
    )

    assert health.healthy is False

    assert (
        health.new_entry_dependencies_ready
        is False
    )


def test_healthy_status_but_missing_funds_not_ready() -> None:
    health = AccountHealthSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=(
            AccountHealthStatus.HEALTHY
        ),
        checked_at=NOW,
        broker_connected=True,
        session_authenticated=True,
        profile_available=True,
        funds_available=False,
    )

    assert health.healthy is True

    assert (
        health.new_entry_dependencies_ready
        is False
    )


# ============================================================
# Eligibility
# ============================================================


def test_allowed_account_eligibility() -> None:
    eligibility = (
        AccountTradingEligibility.allow(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            evaluated_at=NOW,
            available_cash=Decimal(
                "100000"
            ),
            required_cash=Decimal(
                "6500"
            ),
        )
    )

    assert eligibility.allowed is True

    assert (
        eligibility.status
        is AccountEligibilityStatus.ALLOWED
    )

    assert (
        eligibility.reason
        is AccountEligibilityReason.ELIGIBLE
    )


def test_blocked_account_eligibility() -> None:
    eligibility = (
        AccountTradingEligibility.block(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            reason=(
                AccountEligibilityReason
                .INSUFFICIENT_FUNDS
            ),
            evaluated_at=NOW,
            available_cash=Decimal(
                "5000"
            ),
            required_cash=Decimal(
                "6500"
            ),
            message=(
                "insufficient available cash"
            ),
        )
    )

    assert eligibility.allowed is False

    assert (
        eligibility.status
        is AccountEligibilityStatus.BLOCKED
    )

    assert (
        eligibility.reason
        is AccountEligibilityReason
        .INSUFFICIENT_FUNDS
    )


def test_allowed_requires_eligible_reason() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "ALLOWED eligibility requires "
            "ELIGIBLE reason"
        ),
    ):
        AccountTradingEligibility(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                AccountEligibilityStatus
                .ALLOWED
            ),
            reason=(
                AccountEligibilityReason
                .ACCOUNT_BLOCKED
            ),
            evaluated_at=NOW,
        )


def test_blocked_cannot_use_eligible_reason() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "BLOCKED eligibility cannot use "
            "ELIGIBLE reason"
        ),
    ):
        AccountTradingEligibility(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                AccountEligibilityStatus
                .BLOCKED
            ),
            reason=(
                AccountEligibilityReason
                .ELIGIBLE
            ),
            evaluated_at=NOW,
        )


def test_block_factory_rejects_eligible_reason() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "blocked eligibility requires "
            "a blocking reason"
        ),
    ):
        AccountTradingEligibility.block(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            reason=(
                AccountEligibilityReason
                .ELIGIBLE
            ),
            evaluated_at=NOW,
        )


def test_eligibility_negative_cash_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "available_cash cannot be negative"
        ),
    ):
        AccountTradingEligibility.block(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            reason=(
                AccountEligibilityReason
                .INSUFFICIENT_FUNDS
            ),
            evaluated_at=NOW,
            available_cash=Decimal("-1"),
        )


def test_account_eligibility_reasons_are_account_scoped() -> None:
    assert (
        AccountEligibilityReason
        .SESSION_NOT_AUTHENTICATED
        .value
        == "SESSION_NOT_AUTHENTICATED"
    )

    assert (
        AccountEligibilityReason
        .BROKER_UNAVAILABLE
        .value
        == "BROKER_UNAVAILABLE"
    )

    assert (
        AccountEligibilityReason
        .INSUFFICIENT_FUNDS
        .value
        == "INSUFFICIENT_FUNDS"
    )