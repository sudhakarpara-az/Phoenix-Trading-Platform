"""
Phoenix M09-T07 Account State Registry tests.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.account.account_state_registry import (
    AccountStateIdentityError,
    AccountStateNotFoundError,
    AccountStateRegistry,
)
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
from src.account.connectivity_monitor import (
    BrokerConnectivitySnapshot,
)


NOW = datetime(
    2026,
    8,
    8,
    10,
    0,
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)


def make_registry():
    registry = AccountStateRegistry()

    registry.register_account(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        registered_at=NOW,
    )

    return registry


def session():
    return BrokerSessionSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=(
            BrokerSessionStatus
            .AUTHENTICATED
        ),
        authenticated_at=NOW,
        updated_at=NOW,
    )


def profile():
    return AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.ACTIVE
        ),
        fetched_at=NOW,
        trading_enabled=True,
    )


def funds():
    return AccountFundsSnapshot(
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


def connectivity():
    return BrokerConnectivitySnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        connected=True,
        checked_at=NOW,
    )


def health():
    return AccountHealthSnapshot(
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


def eligibility():
    return AccountTradingEligibility(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        status=(
            AccountEligibilityStatus
            .ALLOWED
        ),
        reason=(
            AccountEligibilityReason
            .ELIGIBLE
        ),
        evaluated_at=NOW,
        available_cash=Decimal(
            "100000"
        ),
        required_cash=Decimal(
            "6500"
        ),
    )


# ============================================================
# Registration
# ============================================================


def test_register_account():
    registry = AccountStateRegistry()

    snapshot = (
        registry.register_account(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            registered_at=NOW,
        )
    )

    assert (
        snapshot.account_id
        == ACCOUNT_ID
    )

    assert (
        snapshot.broker
        is BrokerType.DHAN
    )


def test_registered_account_contains():
    registry = make_registry()

    assert (
        registry.contains(
            ACCOUNT_ID
        )
        is True
    )


def test_duplicate_registration_is_idempotent():
    registry = make_registry()

    first = registry.require(
        ACCOUNT_ID
    )

    second = (
        registry.register_account(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            registered_at=NOW,
        )
    )

    assert first == second


def test_unregistered_account_missing():
    registry = AccountStateRegistry()

    assert (
        registry.get(
            ACCOUNT_ID
        )
        is None
    )


def test_require_missing_raises():
    registry = AccountStateRegistry()

    with pytest.raises(
        AccountStateNotFoundError
    ):
        registry.require(
            ACCOUNT_ID
        )


# ============================================================
# Initial aggregate
# ============================================================


def test_initial_state_has_no_substates():
    registry = make_registry()

    state = registry.require(
        ACCOUNT_ID
    )

    assert state.session is None
    assert state.profile is None
    assert state.funds is None
    assert state.connectivity is None
    assert state.health is None
    assert state.eligibility is None


def test_initial_availability_flags_false():
    registry = make_registry()

    state = registry.require(
        ACCOUNT_ID
    )

    assert (
        state.session_available
        is False
    )

    assert (
        state.profile_available
        is False
    )

    assert (
        state.funds_available
        is False
    )

    assert (
        state.connectivity_available
        is False
    )

    assert (
        state.health_available
        is False
    )

    assert (
        state.eligibility_available
        is False
    )


# ============================================================
# Session
# ============================================================


def test_update_session():
    registry = make_registry()

    state = registry.update_session(
        session()
    )

    assert state.session is not None

    assert (
        state.session.status
        is BrokerSessionStatus
        .AUTHENTICATED
    )

    assert (
        state.session_available
        is True
    )


# ============================================================
# Profile
# ============================================================


def test_update_profile():
    registry = make_registry()

    state = registry.update_profile(
        profile()
    )

    assert state.profile is not None

    assert (
        state.profile.account_status
        is BrokerAccountStatus.ACTIVE
    )


# ============================================================
# Funds
# ============================================================


def test_update_funds():
    registry = make_registry()

    state = registry.update_funds(
        funds()
    )

    assert state.funds is not None

    assert (
        state.funds.available_cash
        == Decimal("100000")
    )


# ============================================================
# Connectivity
# ============================================================


def test_update_connectivity():
    registry = make_registry()

    state = (
        registry.update_connectivity(
            connectivity()
        )
    )

    assert (
        state.connectivity
        is not None
    )

    assert (
        state.connectivity.connected
        is True
    )


# ============================================================
# Health
# ============================================================


def test_update_health():
    registry = make_registry()

    state = registry.update_health(
        health()
    )

    assert state.health is not None

    assert (
        state.health.status
        is AccountHealthStatus.HEALTHY
    )


# ============================================================
# Eligibility
# ============================================================


def test_update_eligibility():
    registry = make_registry()

    state = (
        registry.update_eligibility(
            eligibility()
        )
    )

    assert (
        state.eligibility
        is not None
    )

    assert (
        state.eligibility.allowed
        is True
    )


# ============================================================
# Aggregate state preservation
# ============================================================


def test_updates_preserve_previous_substates():
    registry = make_registry()

    registry.update_session(
        session()
    )

    registry.update_profile(
        profile()
    )

    registry.update_funds(
        funds()
    )

    registry.update_connectivity(
        connectivity()
    )

    registry.update_health(
        health()
    )

    state = (
        registry.update_eligibility(
            eligibility()
        )
    )

    assert state.session is not None
    assert state.profile is not None
    assert state.funds is not None

    assert (
        state.connectivity
        is not None
    )

    assert state.health is not None

    assert (
        state.eligibility
        is not None
    )


def test_all_availability_flags_true_after_full_update():
    registry = make_registry()

    registry.update_session(
        session()
    )

    registry.update_profile(
        profile()
    )

    registry.update_funds(
        funds()
    )

    registry.update_connectivity(
        connectivity()
    )

    registry.update_health(
        health()
    )

    registry.update_eligibility(
        eligibility()
    )

    state = registry.require(
        ACCOUNT_ID
    )

    assert (
        state.session_available
        is True
    )

    assert (
        state.profile_available
        is True
    )

    assert (
        state.funds_available
        is True
    )

    assert (
        state.connectivity_available
        is True
    )

    assert (
        state.health_available
        is True
    )

    assert (
        state.eligibility_available
        is True
    )


# ============================================================
# Registration requirement
# ============================================================


def test_update_requires_registered_account():
    registry = AccountStateRegistry()

    with pytest.raises(
        AccountStateNotFoundError,
        match=(
            "account must be registered"
        ),
    ):
        registry.update_session(
            session()
        )


# ============================================================
# Multiple accounts
# ============================================================


def test_registry_supports_multiple_accounts():
    registry = AccountStateRegistry()

    first = ACCOUNT_ID

    second = BrokerAccountId(
        "DHAN-002"
    )

    registry.register_account(
        broker=BrokerType.DHAN,
        account_id=first,
        registered_at=NOW,
    )

    registry.register_account(
        broker=BrokerType.DHAN,
        account_id=second,
        registered_at=NOW,
    )

    assert len(
        registry.accounts()
    ) == 2

    assert (
        registry.contains(first)
        is True
    )

    assert (
        registry.contains(second)
        is True
    )


# ============================================================
# Removal / clearing
# ============================================================


def test_remove_account():
    registry = make_registry()

    assert (
        registry.remove(
            ACCOUNT_ID
        )
        is True
    )

    assert (
        registry.contains(
            ACCOUNT_ID
        )
        is False
    )


def test_remove_missing_returns_false():
    registry = AccountStateRegistry()

    assert (
        registry.remove(
            ACCOUNT_ID
        )
        is False
    )


def test_clear_registry():
    registry = make_registry()

    registry.clear()

    assert (
        registry.accounts()
        == ()
    )


# ============================================================
# Current state retrieval
# ============================================================


def test_require_returns_latest_state():
    registry = make_registry()

    registry.update_session(
        session()
    )

    latest = registry.require(
        ACCOUNT_ID
    )

    assert latest.session is not None