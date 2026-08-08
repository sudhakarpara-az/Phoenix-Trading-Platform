"""
Phoenix M09-T14 Session Expiry / Re-authentication tests.
"""

from datetime import (
    datetime,
    timedelta,
)

import pytest

from src.account.account_types import (
    BrokerAccountId,
    BrokerSessionSnapshot,
    BrokerSessionStatus,
    BrokerType,
)
from src.account.broker_session_manager import (
    BrokerSessionManager,
)
from src.account.session_reauth_service import (
    SessionReauthInProgressError,
    SessionReauthService,
)


NOW = datetime(
    2026,
    8,
    8,
    13,
    30,
)

EXPIRY = (
    NOW
    + timedelta(minutes=30)
)

AFTER_EXPIRY = (
    EXPIRY
    + timedelta(seconds=1)
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)


class FakeSessionProvider:
    def __init__(
        self,
    ):
        self.authenticate_calls = 0
        self.close_calls = 0

        self.error = None

        self.result = (
            BrokerSessionSnapshot(
                broker=BrokerType.DHAN,
                account_id=ACCOUNT_ID,
                status=(
                    BrokerSessionStatus
                    .AUTHENTICATED
                ),
                authenticated_at=NOW,
                expires_at=EXPIRY,
                updated_at=NOW,
            )
        )

    def authenticate(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        self.authenticate_calls += 1

        if self.error is not None:
            raise self.error

        return self.result

    def close(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        self.close_calls += 1


def make_stack():
    provider = FakeSessionProvider()

    manager = BrokerSessionManager(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        provider=provider,
        created_at=NOW,
    )

    service = SessionReauthService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        session_manager=manager,
    )

    return (
        manager,
        provider,
        service,
    )


# ============================================================
# Identity
# ============================================================


def test_reauth_service_identity():
    _, _, service = (
        make_stack()
    )

    assert (
        service.broker
        is BrokerType.DHAN
    )

    assert (
        service.account_id
        == ACCOUNT_ID
    )


# ============================================================
# Initial authentication
# ============================================================


def test_not_initialized_session_is_authenticated():
    manager, provider, service = (
        make_stack()
    )

    result = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert (
        result.reauth_attempted
        is True
    )

    assert (
        result.reauth_succeeded
        is True
    )

    assert (
        result.authenticated
        is True
    )

    assert (
        manager.status
        is BrokerSessionStatus
        .AUTHENTICATED
    )

    assert (
        provider.authenticate_calls
        == 1
    )


# ============================================================
# Existing authenticated session
# ============================================================


def test_valid_authenticated_session_does_not_reauthenticate():
    manager, provider, service = (
        make_stack()
    )

    manager.authenticate(
        requested_at=NOW
    )

    assert (
        provider.authenticate_calls
        == 1
    )

    result = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert (
        result.reauth_attempted
        is False
    )

    assert (
        result.authenticated
        is True
    )

    assert (
        provider.authenticate_calls
        == 1
    )


# ============================================================
# Expiry detection
# ============================================================


def test_expired_session_is_detected():
    manager, _, service = (
        make_stack()
    )

    manager.authenticate(
        requested_at=NOW
    )

    manager.refresh_expiry_state(
        checked_at=EXPIRY
    )

    assert (
        manager.status
        is BrokerSessionStatus.EXPIRED
    )


def test_expired_session_reauthenticates():
    manager, provider, service = (
        make_stack()
    )

    manager.authenticate(
        requested_at=NOW
    )

    provider.result = (
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            authenticated_at=(
                AFTER_EXPIRY
            ),
            updated_at=(
                AFTER_EXPIRY
            ),
            expires_at=(
                AFTER_EXPIRY
                + timedelta(hours=1)
            ),
        )
    )

    result = (
        service.ensure_authenticated(
            checked_at=AFTER_EXPIRY
        )
    )

    assert (
        result.reauth_attempted
        is True
    )

    assert (
        result.reauth_succeeded
        is True
    )

    assert (
        result.authenticated
        is True
    )

    assert (
        provider.authenticate_calls
        == 2
    )


# ============================================================
# Failed session recovery
# ============================================================


def test_failed_session_can_reauthenticate():
    manager, provider, service = (
        make_stack()
    )

    manager.mark_failed(
        message="temporary failure",
        failed_at=NOW,
    )

    provider.result = (
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            authenticated_at=NOW,
            updated_at=NOW,
        )
    )

    result = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert (
        result.reauth_succeeded
        is True
    )

    assert (
        manager.status
        is BrokerSessionStatus
        .AUTHENTICATED
    )


# ============================================================
# Failed re-authentication
# ============================================================


def test_reauthentication_failure_stays_blocked():
    manager, provider, service = (
        make_stack()
    )

    manager.mark_failed(
        message="previous failure",
        failed_at=NOW,
    )

    provider.error = RuntimeError(
        "authentication unavailable"
    )

    result = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert (
        result.reauth_attempted
        is True
    )

    assert (
        result.reauth_succeeded
        is False
    )

    assert (
        result.authenticated
        is False
    )

    assert (
        manager.status
        is BrokerSessionStatus.FAILED
    )

    assert (
        result.usable_for_new_entries
        is False
    )


def test_failed_reauth_records_last_result():
    manager, provider, service = (
        make_stack()
    )

    manager.mark_failed(
        message="previous failure",
        failed_at=NOW,
    )

    provider.error = RuntimeError(
        "auth failed"
    )

    result = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert (
        service.last_result
        == result
    )

    assert (
        result.message
        is not None
    )


# ============================================================
# Explicit re-auth
# ============================================================


def test_explicit_reauth_on_authenticated_session_is_noop():
    manager, provider, service = (
        make_stack()
    )

    manager.authenticate(
        requested_at=NOW
    )

    result = service.reauthenticate(
        requested_at=NOW
    )

    assert (
        result.reauth_attempted
        is False
    )

    assert (
        result.authenticated
        is True
    )

    assert (
        provider.authenticate_calls
        == 1
    )


# ============================================================
# Closed session
# ============================================================


def test_closed_session_does_not_reauthenticate():
    manager, provider, service = (
        make_stack()
    )

    manager.close(
        requested_at=NOW
    )

    result = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert (
        result.reauth_attempted
        is False
    )

    assert (
        result.authenticated
        is False
    )

    assert (
        manager.status
        is BrokerSessionStatus.CLOSED
    )

    assert (
        provider.authenticate_calls
        == 0
    )


# ============================================================
# Entry readiness
# ============================================================


def test_successful_reauth_restores_new_entry_readiness():
    manager, provider, service = (
        make_stack()
    )

    manager.mark_failed(
        message="expired token",
        failed_at=NOW,
    )

    provider.result = (
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            authenticated_at=NOW,
            updated_at=NOW,
        )
    )

    result = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert (
        result.usable_for_new_entries
        is True
    )


def test_failed_reauth_keeps_new_entry_readiness_false():
    manager, provider, service = (
        make_stack()
    )

    manager.mark_failed(
        message="expired token",
        failed_at=NOW,
    )

    provider.error = RuntimeError(
        "cannot authenticate"
    )

    result = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert (
        result.usable_for_new_entries
        is False
    )


# ============================================================
# Repeated calls after success
# ============================================================


def test_second_ensure_after_success_does_not_reauthenticate_again():
    manager, provider, service = (
        make_stack()
    )

    first = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    second = (
        service.ensure_authenticated(
            checked_at=NOW
        )
    )

    assert first.authenticated is True
    assert second.authenticated is True

    assert (
        provider.authenticate_calls
        == 1
    )


# ============================================================
# Concurrent lock behavior
# ============================================================


def test_reauth_lock_rejects_concurrent_attempt():
    _, _, service = (
        make_stack()
    )

    acquired = (
        service._reauth_lock.acquire(
            blocking=False
        )
    )

    assert acquired is True

    try:
        with pytest.raises(
            SessionReauthInProgressError,
            match=(
                "re-authentication "
                "already in progress"
            ),
        ):
            service.reauthenticate(
                requested_at=NOW
            )

    finally:
        service._reauth_lock.release()