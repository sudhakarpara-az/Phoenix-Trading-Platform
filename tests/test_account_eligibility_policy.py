"""
Phoenix M09-T05 Account Trading Eligibility tests.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.account.account_eligibility_policy import (
    AccountTradingEligibilityPolicy,
    BrokerConnectivitySnapshot,
)
from src.account.account_types import (
    AccountEligibilityReason,
    AccountEligibilityStatus,
    AccountFundsSnapshot,
    AccountProfile,
    BrokerAccountId,
    BrokerAccountStatus,
    BrokerSessionSnapshot,
    BrokerSessionStatus,
    BrokerType,
)
from src.account.funds_provider import (
    AccountFundsService,
)


NOW = datetime(
    2026,
    8,
    8,
    9,
    40,
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)

REQUIRED_CASH = Decimal(
    "6500"
)


class StaticFundsProvider:
    def __init__(
        self,
        snapshot,
    ):
        self.snapshot = snapshot

    def fetch_funds(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        del broker
        del account_id
        del requested_at

        return self.snapshot


class FailingFundsProvider:
    def fetch_funds(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        del broker
        del account_id
        del requested_at

        raise RuntimeError(
            "funds unavailable"
        )


def session(
    status=(
        BrokerSessionStatus.AUTHENTICATED
    ),
):
    kwargs = {}

    if (
        status
        is BrokerSessionStatus.AUTHENTICATED
    ):
        kwargs[
            "authenticated_at"
        ] = NOW

    if (
        status
        is BrokerSessionStatus.EXPIRED
    ):
        kwargs[
            "authenticated_at"
        ] = NOW

    if (
        status
        is BrokerSessionStatus.FAILED
    ):
        kwargs[
            "failure_message"
        ] = "authentication failed"

    return BrokerSessionSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=status,
        updated_at=NOW,
        **kwargs,
    )


def profile(
    status=(
        BrokerAccountStatus.ACTIVE
    ),
    *,
    trading_enabled=True,
):
    return AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=status,
        fetched_at=NOW,
        trading_enabled=(
            trading_enabled
        ),
    )


def funds_service(
    available_cash=Decimal(
        "100000"
    ),
):
    provider = StaticFundsProvider(
        AccountFundsSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            available_cash=(
                available_cash
            ),
            available_margin=Decimal(
                "0"
            ),
            utilized_margin=Decimal(
                "0"
            ),
            fetched_at=NOW,
        )
    )

    service = AccountFundsService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        provider=provider,
    )

    service.refresh(
        requested_at=NOW
    )

    return service


def empty_funds_service():
    return AccountFundsService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        provider=(
            FailingFundsProvider()
        ),
    )


def connectivity(
    *,
    connected=True,
):
    return BrokerConnectivitySnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        connected=connected,
        checked_at=NOW,
    )


def evaluate(
    *,
    session_snapshot=None,
    account_profile=None,
    funds=None,
    broker_connectivity=None,
    required_cash=REQUIRED_CASH,
):
    policy = (
        AccountTradingEligibilityPolicy()
    )

    return policy.evaluate(
        session=(
            session_snapshot
            or session()
        ),
        profile=(
            account_profile
            if account_profile is not None
            else profile()
        ),
        funds=(
            funds
            or funds_service()
        ),
        connectivity=(
            broker_connectivity
            or connectivity()
        ),
        required_cash=required_cash,
        evaluated_at=NOW,
    )


# ============================================================
# Allowed
# ============================================================


def test_account_allowed_when_all_dependencies_ready():
    result = evaluate()

    assert (
        result.status
        is AccountEligibilityStatus.ALLOWED
    )

    assert (
        result.reason
        is AccountEligibilityReason.ELIGIBLE
    )

    assert result.allowed is True

    assert (
        result.available_cash
        == Decimal("100000")
    )

    assert (
        result.required_cash
        == REQUIRED_CASH
    )


def test_exact_cash_is_allowed():
    result = evaluate(
        funds=funds_service(
            available_cash=(
                REQUIRED_CASH
            )
        )
    )

    assert result.allowed is True


def test_zero_required_cash_is_allowed():
    result = evaluate(
        required_cash=Decimal("0")
    )

    assert result.allowed is True


# ============================================================
# Connectivity
# ============================================================


def test_broker_unavailable_blocks_entry():
    result = evaluate(
        broker_connectivity=(
            connectivity(
                connected=False
            )
        )
    )

    assert result.allowed is False

    assert (
        result.reason
        is AccountEligibilityReason
        .BROKER_UNAVAILABLE
    )


# ============================================================
# Session
# ============================================================


@pytest.mark.parametrize(
    "status,reason",
    [
        (
            BrokerSessionStatus
            .NOT_INITIALIZED,
            AccountEligibilityReason
            .SESSION_NOT_AUTHENTICATED,
        ),
        (
            BrokerSessionStatus
            .AUTHENTICATING,
            AccountEligibilityReason
            .SESSION_NOT_AUTHENTICATED,
        ),
        (
            BrokerSessionStatus.EXPIRED,
            AccountEligibilityReason
            .SESSION_EXPIRED,
        ),
        (
            BrokerSessionStatus.FAILED,
            AccountEligibilityReason
            .SESSION_FAILED,
        ),
        (
            BrokerSessionStatus.CLOSED,
            AccountEligibilityReason
            .SESSION_NOT_AUTHENTICATED,
        ),
    ],
)
def test_invalid_session_blocks_entry(
    status,
    reason,
):
    result = evaluate(
        session_snapshot=(
            session(status)
        )
    )

    assert result.allowed is False

    assert (
        result.reason
        is reason
    )


# ============================================================
# Profile
# ============================================================


def test_missing_profile_blocks_entry():
    policy = (
        AccountTradingEligibilityPolicy()
    )

    result = policy.evaluate(
        session=session(),
        profile=None,
        funds=funds_service(),
        connectivity=connectivity(),
        required_cash=REQUIRED_CASH,
        evaluated_at=NOW,
    )

    assert result.allowed is False

    assert (
        result.reason
        is AccountEligibilityReason
        .PROFILE_UNAVAILABLE
    )


def test_unknown_account_status_blocks_entry():
    result = evaluate(
        account_profile=profile(
            BrokerAccountStatus.UNKNOWN
        )
    )

    assert (
        result.reason
        is AccountEligibilityReason
        .ACCOUNT_STATUS_UNKNOWN
    )


def test_inactive_account_blocks_entry():
    result = evaluate(
        account_profile=profile(
            BrokerAccountStatus.INACTIVE
        )
    )

    assert (
        result.reason
        is AccountEligibilityReason
        .ACCOUNT_INACTIVE
    )


def test_blocked_account_blocks_entry():
    result = evaluate(
        account_profile=profile(
            BrokerAccountStatus.BLOCKED
        )
    )

    assert (
        result.reason
        is AccountEligibilityReason
        .ACCOUNT_BLOCKED
    )


def test_trading_disabled_blocks_entry():
    result = evaluate(
        account_profile=profile(
            BrokerAccountStatus.ACTIVE,
            trading_enabled=False,
        )
    )

    assert (
        result.reason
        is AccountEligibilityReason
        .TRADING_NOT_ENABLED
    )


# ============================================================
# Funds
# ============================================================


def test_missing_funds_snapshot_blocks_entry():
    result = evaluate(
        funds=empty_funds_service()
    )

    assert result.allowed is False

    assert (
        result.reason
        is AccountEligibilityReason
        .FUNDS_UNAVAILABLE
    )


def test_insufficient_funds_blocks_entry():
    result = evaluate(
        funds=funds_service(
            available_cash=Decimal(
                "5000"
            )
        )
    )

    assert result.allowed is False

    assert (
        result.reason
        is AccountEligibilityReason
        .INSUFFICIENT_FUNDS
    )

    assert (
        result.available_cash
        == Decimal("5000")
    )

    assert (
        result.required_cash
        == REQUIRED_CASH
    )


# ============================================================
# Validation
# ============================================================


def test_negative_required_cash_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "required cash cannot be negative"
        ),
    ):
        evaluate(
            required_cash=Decimal("-1")
        )


def test_connectivity_account_mismatch_rejected():
    bad = (
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=BrokerAccountId(
                "OTHER"
            ),
            connected=True,
            checked_at=NOW,
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "connectivity account does not "
            "match session account"
        ),
    ):
        evaluate(
            broker_connectivity=bad
        )


def test_profile_account_mismatch_rejected():
    bad = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=BrokerAccountId(
            "OTHER"
        ),
        account_status=(
            BrokerAccountStatus.ACTIVE
        ),
        fetched_at=NOW,
        trading_enabled=True,
    )

    with pytest.raises(
        ValueError,
        match=(
            "profile account does not "
            "match session account"
        ),
    ):
        evaluate(
            account_profile=bad
        )


def test_funds_account_mismatch_rejected():
    provider = StaticFundsProvider(
        AccountFundsSnapshot(
            broker=BrokerType.DHAN,
            account_id=BrokerAccountId(
                "OTHER"
            ),
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
    )

    bad_funds = AccountFundsService(
        broker=BrokerType.DHAN,
        account_id=BrokerAccountId(
            "OTHER"
        ),
        provider=provider,
    )

    bad_funds.refresh(
        requested_at=NOW
    )

    with pytest.raises(
        ValueError,
        match=(
            "funds account does not "
            "match session account"
        ),
    ):
        evaluate(
            funds=bad_funds
        )


# ============================================================
# Priority ordering
# ============================================================


def test_connectivity_failure_has_priority_over_session():
    result = evaluate(
        session_snapshot=session(
            BrokerSessionStatus.EXPIRED
        ),
        broker_connectivity=(
            connectivity(
                connected=False
            )
        ),
    )

    assert (
        result.reason
        is AccountEligibilityReason
        .BROKER_UNAVAILABLE
    )


def test_session_failure_has_priority_over_profile():
    result = evaluate(
        session_snapshot=session(
            BrokerSessionStatus.EXPIRED
        ),
        account_profile=profile(
            BrokerAccountStatus.BLOCKED
        ),
    )

    assert (
        result.reason
        is AccountEligibilityReason
        .SESSION_EXPIRED
    )


def test_profile_failure_has_priority_over_funds():
    result = evaluate(
        account_profile=profile(
            BrokerAccountStatus.BLOCKED
        ),
        funds=funds_service(
            Decimal("1")
        ),
    )

    assert (
        result.reason
        is AccountEligibilityReason
        .ACCOUNT_BLOCKED
    )


# ============================================================
# Result messages
# ============================================================


def test_insufficient_funds_has_message():
    result = evaluate(
        funds=funds_service(
            Decimal("1")
        )
    )

    assert (
        result.message
        == "insufficient available cash"
    )


def test_allowed_result_has_no_block_message():
    result = evaluate()

    assert (
        result.message
        is None
    )