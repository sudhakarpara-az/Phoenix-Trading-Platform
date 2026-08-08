"""
Phoenix M09-T03 Account Profile Provider tests.
"""

from datetime import (
    datetime,
    timedelta,
)

import pytest

from src.account.account_profile_provider import (
    AccountProfileFetchError,
    AccountProfileService,
)
from src.account.account_types import (
    AccountProfile,
    BrokerAccountId,
    BrokerAccountStatus,
    BrokerType,
)


NOW = datetime(
    2026,
    8,
    8,
    9,
    30,
)

LATER = (
    NOW
    + timedelta(minutes=5)
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)


class FakeAccountProfileProvider:
    def __init__(
        self,
    ) -> None:
        self.calls = []

        self.result = AccountProfile(
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

        self.error = None

    def fetch_profile(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        self.calls.append(
            (
                broker,
                account_id,
                requested_at,
            )
        )

        if self.error is not None:
            raise self.error

        return self.result


def make_service(
    provider=None,
):
    provider = (
        provider
        or FakeAccountProfileProvider()
    )

    service = AccountProfileService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        provider=provider,
    )

    return service, provider


# ============================================================
# Initial state
# ============================================================


def test_profile_initially_unavailable():
    service, _ = make_service()

    assert (
        service.latest_profile
        is None
    )

    assert (
        service.profile_available
        is False
    )

    assert (
        service.last_failure
        is None
    )


def test_initial_account_status_is_unknown():
    service, _ = make_service()

    assert (
        service.account_status()
        is BrokerAccountStatus.UNKNOWN
    )


def test_initial_state_blocks_new_entries():
    service, _ = make_service()

    assert (
        service.requires_new_entry_block()
        is True
    )


def test_service_preserves_broker():
    service, _ = make_service()

    assert (
        service.broker
        is BrokerType.DHAN
    )


def test_service_preserves_account_id():
    service, _ = make_service()

    assert (
        service.account_id
        == ACCOUNT_ID
    )


# ============================================================
# Refresh
# ============================================================


def test_refresh_profile_success():
    service, provider = (
        make_service()
    )

    profile = service.refresh(
        requested_at=NOW
    )

    assert (
        profile.account_status
        is BrokerAccountStatus.ACTIVE
    )

    assert (
        service.latest_profile
        == profile
    )

    assert (
        service.profile_available
        is True
    )

    assert (
        service.last_failure
        is None
    )

    assert (
        len(provider.calls)
        == 1
    )


def test_provider_receives_account_identity():
    service, provider = (
        make_service()
    )

    service.refresh(
        requested_at=NOW
    )

    (
        broker,
        account_id,
        requested_at,
    ) = provider.calls[0]

    assert broker is BrokerType.DHAN

    assert (
        account_id
        == ACCOUNT_ID
    )

    assert (
        requested_at
        == NOW
    )


def test_active_trading_enabled_profile_is_eligible():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.account_active
        is True
    )

    assert (
        service.trading_enabled
        is True
    )

    assert (
        service.eligible_account_state
        is True
    )

    assert (
        service.requires_new_entry_block()
        is False
    )


# ============================================================
# Account state
# ============================================================


def test_active_but_trading_disabled_blocks_entries():
    provider = (
        FakeAccountProfileProvider()
    )

    provider.result = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.ACTIVE
        ),
        fetched_at=NOW,
        trading_enabled=False,
    )

    service, _ = make_service(
        provider
    )

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.account_active
        is True
    )

    assert (
        service.trading_enabled
        is False
    )

    assert (
        service.eligible_account_state
        is False
    )

    assert (
        service.requires_new_entry_block()
        is True
    )


def test_inactive_account_blocks_entries():
    provider = (
        FakeAccountProfileProvider()
    )

    provider.result = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.INACTIVE
        ),
        fetched_at=NOW,
        trading_enabled=True,
    )

    service, _ = make_service(
        provider
    )

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.account_status()
        is BrokerAccountStatus.INACTIVE
    )

    assert (
        service.account_active
        is False
    )

    assert (
        service.requires_new_entry_block()
        is True
    )


def test_blocked_account_blocks_entries():
    provider = (
        FakeAccountProfileProvider()
    )

    provider.result = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.BLOCKED
        ),
        fetched_at=NOW,
        trading_enabled=True,
    )

    service, _ = make_service(
        provider
    )

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.account_status()
        is BrokerAccountStatus.BLOCKED
    )

    assert (
        service.requires_new_entry_block()
        is True
    )


def test_unknown_account_status_blocks_entries():
    provider = (
        FakeAccountProfileProvider()
    )

    provider.result = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.UNKNOWN
        ),
        fetched_at=NOW,
        trading_enabled=True,
    )

    service, _ = make_service(
        provider
    )

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.account_status()
        is BrokerAccountStatus.UNKNOWN
    )

    assert (
        service.requires_new_entry_block()
        is True
    )


# ============================================================
# Failure handling
# ============================================================


def test_provider_failure_raises_profile_error():
    provider = (
        FakeAccountProfileProvider()
    )

    provider.error = RuntimeError(
        "profile endpoint unavailable"
    )

    service, _ = make_service(
        provider
    )

    with pytest.raises(
        AccountProfileFetchError,
        match=(
            "account profile fetch failed"
        ),
    ):
        service.refresh(
            requested_at=NOW
        )

    assert (
        service.last_failure
        == "profile endpoint unavailable"
    )


def test_first_fetch_failure_leaves_profile_unavailable():
    provider = (
        FakeAccountProfileProvider()
    )

    provider.error = RuntimeError(
        "broker unavailable"
    )

    service, _ = make_service(
        provider
    )

    with pytest.raises(
        AccountProfileFetchError
    ):
        service.refresh(
            requested_at=NOW
        )

    assert (
        service.latest_profile
        is None
    )

    assert (
        service.profile_available
        is False
    )

    assert (
        service.requires_new_entry_block()
        is True
    )


def test_refresh_failure_retains_last_good_profile():
    provider = (
        FakeAccountProfileProvider()
    )

    service, _ = make_service(
        provider
    )

    first = service.refresh(
        requested_at=NOW
    )

    provider.error = RuntimeError(
        "temporary profile failure"
    )

    with pytest.raises(
        AccountProfileFetchError
    ):
        service.refresh(
            requested_at=LATER
        )

    assert (
        service.latest_profile
        == first
    )

    assert (
        service.last_failure
        == "temporary profile failure"
    )


def test_successful_refresh_clears_previous_failure():
    provider = (
        FakeAccountProfileProvider()
    )

    service, _ = make_service(
        provider
    )

    provider.error = RuntimeError(
        "temporary failure"
    )

    with pytest.raises(
        AccountProfileFetchError
    ):
        service.refresh(
            requested_at=NOW
        )

    assert (
        service.last_failure
        == "temporary failure"
    )

    provider.error = None

    service.refresh(
        requested_at=LATER
    )

    assert (
        service.last_failure
        is None
    )


# ============================================================
# Provider identity validation
# ============================================================


def test_provider_account_mismatch_rejected():
    provider = (
        FakeAccountProfileProvider()
    )

    provider.result = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=BrokerAccountId(
            "OTHER-ACCOUNT"
        ),
        account_status=(
            BrokerAccountStatus.ACTIVE
        ),
        fetched_at=NOW,
        trading_enabled=True,
    )

    service, _ = make_service(
        provider
    )

    with pytest.raises(
        AccountProfileFetchError,
        match=(
            "returned mismatched account"
        ),
    ):
        service.refresh(
            requested_at=NOW
        )

    assert (
        service.latest_profile
        is None
    )

    assert (
        service.last_failure
        == (
            "account profile provider "
            "returned mismatched account"
        )
    )


# ============================================================
# Multiple refreshes
# ============================================================


def test_new_successful_profile_replaces_previous_profile():
    provider = (
        FakeAccountProfileProvider()
    )

    service, _ = make_service(
        provider
    )

    first = service.refresh(
        requested_at=NOW
    )

    provider.result = AccountProfile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        account_status=(
            BrokerAccountStatus.INACTIVE
        ),
        fetched_at=LATER,
        client_name="Phoenix Trader",
        trading_enabled=False,
    )

    second = service.refresh(
        requested_at=LATER
    )

    assert (
        second != first
    )

    assert (
        service.latest_profile
        == second
    )

    assert (
        service.account_status()
        is BrokerAccountStatus.INACTIVE
    )

    assert (
        service.requires_new_entry_block()
        is True
    )