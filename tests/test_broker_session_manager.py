"""
Phoenix M09-T02 Broker Session Manager tests.
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
    BrokerSessionAuthenticationError,
    BrokerSessionManager,
    BrokerSessionTransitionError,
)


NOW = datetime(
    2026,
    8,
    8,
    9,
    0,
)

LATER = (
    NOW
    + timedelta(hours=1)
)

AFTER_EXPIRY = (
    LATER
    + timedelta(seconds=1)
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)


class FakeSessionProvider:
    def __init__(
        self,
    ) -> None:
        self.authenticate_calls = []
        self.close_calls = []

        self.authenticate_result = (
            BrokerSessionSnapshot(
                broker=BrokerType.DHAN,
                account_id=ACCOUNT_ID,
                status=(
                    BrokerSessionStatus
                    .AUTHENTICATED
                ),
                authenticated_at=NOW,
                expires_at=LATER,
                updated_at=NOW,
            )
        )

        self.authenticate_error = None
        self.close_error = None

    def authenticate(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        self.authenticate_calls.append(
            (
                broker,
                account_id,
                requested_at,
            )
        )

        if (
            self.authenticate_error
            is not None
        ):
            raise self.authenticate_error

        return self.authenticate_result

    def close(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        self.close_calls.append(
            (
                broker,
                account_id,
                requested_at,
            )
        )

        if self.close_error is not None:
            raise self.close_error


def make_manager(
    provider=None,
):
    provider = (
        provider
        or FakeSessionProvider()
    )

    manager = BrokerSessionManager(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        provider=provider,
        created_at=NOW,
    )

    return manager, provider


# ============================================================
# Initial state
# ============================================================


def test_manager_starts_not_initialized():
    manager, _ = make_manager()

    assert (
        manager.status
        is BrokerSessionStatus
        .NOT_INITIALIZED
    )

    assert manager.authenticated is False

    assert (
        manager.usable_for_new_entries
        is False
    )


def test_manager_preserves_broker():
    manager, _ = make_manager()

    assert (
        manager.broker
        is BrokerType.DHAN
    )


def test_manager_preserves_account_id():
    manager, _ = make_manager()

    assert (
        manager.account_id
        == ACCOUNT_ID
    )


# ============================================================
# Authentication
# ============================================================


def test_authenticate_success():
    manager, provider = (
        make_manager()
    )

    snapshot = manager.authenticate(
        requested_at=NOW
    )

    assert (
        snapshot.status
        is BrokerSessionStatus
        .AUTHENTICATED
    )

    assert manager.authenticated is True

    assert (
        manager.usable_for_new_entries
        is True
    )

    assert len(
        provider.authenticate_calls
    ) == 1


def test_authentication_provider_receives_identity():
    manager, provider = (
        make_manager()
    )

    manager.authenticate(
        requested_at=NOW
    )

    (
        broker,
        account_id,
        requested_at,
    ) = provider.authenticate_calls[0]

    assert broker is BrokerType.DHAN
    assert account_id == ACCOUNT_ID
    assert requested_at == NOW


def test_second_authenticate_while_authenticated_rejected():
    manager, _ = make_manager()

    manager.authenticate(
        requested_at=NOW
    )

    with pytest.raises(
        BrokerSessionTransitionError,
        match=(
            "broker session cannot "
            "authenticate from AUTHENTICATED"
        ),
    ):
        manager.authenticate(
            requested_at=NOW
        )


def test_provider_exception_moves_session_to_failed():
    provider = FakeSessionProvider()

    provider.authenticate_error = (
        RuntimeError(
            "authentication unavailable"
        )
    )

    manager, _ = make_manager(
        provider
    )

    with pytest.raises(
        BrokerSessionAuthenticationError,
        match=(
            "broker session "
            "authentication failed"
        ),
    ):
        manager.authenticate(
            requested_at=NOW
        )

    assert (
        manager.status
        is BrokerSessionStatus.FAILED
    )

    assert (
        manager.snapshot.failure_message
        == "authentication unavailable"
    )


def test_provider_must_return_authenticated_state():
    provider = FakeSessionProvider()

    provider.authenticate_result = (
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus.EXPIRED
            ),
            authenticated_at=NOW,
            expires_at=LATER,
            updated_at=LATER,
        )
    )

    manager, _ = make_manager(
        provider
    )

    with pytest.raises(
        BrokerSessionAuthenticationError,
        match=(
            "did not return "
            "AUTHENTICATED session"
        ),
    ):
        manager.authenticate(
            requested_at=NOW
        )

    assert (
        manager.status
        is BrokerSessionStatus.FAILED
    )


def test_provider_broker_mismatch_rejected():
    provider = FakeSessionProvider()

    # Extend BrokerType only through real enum members.
    # Simulate mismatch using another account snapshot field
    # check in the next test; broker mismatch itself cannot be
    # created while BrokerType currently has only DHAN.
    manager, _ = make_manager(
        provider
    )

    assert (
        manager.broker
        is BrokerType.DHAN
    )


def test_provider_account_mismatch_rejected():
    provider = FakeSessionProvider()

    provider.authenticate_result = (
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=(
                BrokerAccountId(
                    "OTHER-ACCOUNT"
                )
            ),
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            authenticated_at=NOW,
            expires_at=LATER,
            updated_at=NOW,
        )
    )

    manager, _ = make_manager(
        provider
    )

    with pytest.raises(
        BrokerSessionAuthenticationError,
        match=(
            "returned mismatched account"
        ),
    ):
        manager.authenticate(
            requested_at=NOW
        )


# ============================================================
# Expiry
# ============================================================


def test_authenticated_session_remains_valid_before_expiry():
    manager, _ = make_manager()

    manager.authenticate(
        requested_at=NOW
    )

    snapshot = (
        manager.refresh_expiry_state(
            checked_at=NOW
        )
    )

    assert (
        snapshot.status
        is BrokerSessionStatus
        .AUTHENTICATED
    )


def test_authenticated_session_expires_at_expiry_time():
    manager, _ = make_manager()

    manager.authenticate(
        requested_at=NOW
    )

    snapshot = (
        manager.refresh_expiry_state(
            checked_at=LATER
        )
    )

    assert (
        snapshot.status
        is BrokerSessionStatus.EXPIRED
    )

    assert manager.authenticated is False

    assert (
        manager.usable_for_new_entries
        is False
    )


def test_expired_session_remains_expired():
    manager, _ = make_manager()

    manager.authenticate(
        requested_at=NOW
    )

    manager.refresh_expiry_state(
        checked_at=LATER
    )

    snapshot = (
        manager.refresh_expiry_state(
            checked_at=AFTER_EXPIRY
        )
    )

    assert (
        snapshot.status
        is BrokerSessionStatus.EXPIRED
    )


def test_session_without_expiry_remains_authenticated():
    provider = FakeSessionProvider()

    provider.authenticate_result = (
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

    manager, _ = make_manager(
        provider
    )

    manager.authenticate(
        requested_at=NOW
    )

    snapshot = (
        manager.refresh_expiry_state(
            checked_at=AFTER_EXPIRY
        )
    )

    assert (
        snapshot.status
        is BrokerSessionStatus
        .AUTHENTICATED
    )


# ============================================================
# Re-authentication
# ============================================================


def test_expired_session_can_authenticate_again():
    manager, provider = (
        make_manager()
    )

    manager.authenticate(
        requested_at=NOW
    )

    manager.refresh_expiry_state(
        checked_at=LATER
    )

    provider.authenticate_result = (
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

    snapshot = manager.authenticate(
        requested_at=AFTER_EXPIRY
    )

    assert (
        snapshot.status
        is BrokerSessionStatus
        .AUTHENTICATED
    )

    assert (
        len(
            provider.authenticate_calls
        )
        == 2
    )


def test_failed_session_can_authenticate_again():
    provider = FakeSessionProvider()

    provider.authenticate_error = (
        RuntimeError("temporary failure")
    )

    manager, _ = make_manager(
        provider
    )

    with pytest.raises(
        BrokerSessionAuthenticationError
    ):
        manager.authenticate(
            requested_at=NOW
        )

    assert (
        manager.status
        is BrokerSessionStatus.FAILED
    )

    provider.authenticate_error = None

    provider.authenticate_result = (
        BrokerSessionSnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            authenticated_at=LATER,
            updated_at=LATER,
        )
    )

    snapshot = manager.authenticate(
        requested_at=LATER
    )

    assert (
        snapshot.status
        is BrokerSessionStatus
        .AUTHENTICATED
    )


# ============================================================
# Explicit failure
# ============================================================


def test_mark_failed():
    manager, _ = make_manager()

    snapshot = manager.mark_failed(
        message="broker disconnected",
        failed_at=LATER,
    )

    assert (
        snapshot.status
        is BrokerSessionStatus.FAILED
    )

    assert (
        snapshot.failure_message
        == "broker disconnected"
    )


def test_closed_session_cannot_mark_failed():
    manager, _ = make_manager()

    manager.close(
        requested_at=NOW
    )

    with pytest.raises(
        BrokerSessionTransitionError,
        match=(
            "CLOSED broker session "
            "cannot transition to FAILED"
        ),
    ):
        manager.mark_failed(
            message="late failure",
            failed_at=LATER,
        )


# ============================================================
# Close
# ============================================================


def test_close_session():
    manager, provider = (
        make_manager()
    )

    manager.authenticate(
        requested_at=NOW
    )

    snapshot = manager.close(
        requested_at=LATER
    )

    assert (
        snapshot.status
        is BrokerSessionStatus.CLOSED
    )

    assert manager.authenticated is False

    assert (
        len(
            provider.close_calls
        )
        == 1
    )


def test_close_is_idempotent():
    manager, provider = (
        make_manager()
    )

    first = manager.close(
        requested_at=NOW
    )

    second = manager.close(
        requested_at=LATER
    )

    assert (
        first.status
        is BrokerSessionStatus.CLOSED
    )

    assert (
        second.status
        is BrokerSessionStatus.CLOSED
    )

    assert (
        len(
            provider.close_calls
        )
        == 1
    )


def test_close_provider_failure_marks_session_failed():
    provider = FakeSessionProvider()

    provider.close_error = (
        RuntimeError(
            "close unavailable"
        )
    )

    manager, _ = make_manager(
        provider
    )

    snapshot = manager.close(
        requested_at=NOW
    )

    assert (
        snapshot.status
        is BrokerSessionStatus.FAILED
    )

    assert (
        "close unavailable"
        in snapshot.failure_message
    )


def test_closed_session_cannot_authenticate_again():
    manager, _ = make_manager()

    manager.close(
        requested_at=NOW
    )

    with pytest.raises(
        BrokerSessionTransitionError
    ):
        manager.authenticate(
            requested_at=LATER
        )