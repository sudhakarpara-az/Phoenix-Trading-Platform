"""
Phoenix M09-T06 Broker Connectivity Monitor tests.
"""

from datetime import (
    datetime,
    timedelta,
)

import pytest

from src.account.account_types import (
    BrokerAccountId,
    BrokerType,
)
from src.account.connectivity_monitor import (
    BrokerConnectivityCheckError,
    BrokerConnectivityMonitor,
    BrokerConnectivitySnapshot,
)


NOW = datetime(
    2026,
    8,
    8,
    9,
    45,
)

LATER = (
    NOW
    + timedelta(minutes=1)
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)


class FakeConnectivityProvider:
    def __init__(
        self,
    ) -> None:
        self.calls = []

        self.result = (
            BrokerConnectivitySnapshot(
                broker=BrokerType.DHAN,
                account_id=ACCOUNT_ID,
                connected=True,
                checked_at=NOW,
                latency_ms=15.5,
            )
        )

        self.error = None

    def check_connectivity(
        self,
        *,
        broker,
        account_id,
        checked_at,
    ):
        self.calls.append(
            (
                broker,
                account_id,
                checked_at,
            )
        )

        if self.error is not None:
            raise self.error

        return self.result


def make_monitor(
    provider=None,
):
    provider = (
        provider
        or FakeConnectivityProvider()
    )

    monitor = BrokerConnectivityMonitor(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        provider=provider,
    )

    return monitor, provider


# ============================================================
# Snapshot model
# ============================================================


def test_connectivity_snapshot():
    snapshot = BrokerConnectivitySnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        connected=True,
        checked_at=NOW,
        latency_ms=10,
    )

    assert snapshot.connected is True

    assert (
        snapshot.latency_ms
        == 10
    )


def test_negative_latency_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "connectivity latency "
            "cannot be negative"
        ),
    ):
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            connected=True,
            checked_at=NOW,
            latency_ms=-1,
        )


def test_connectivity_message_trimmed():
    snapshot = BrokerConnectivitySnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        connected=False,
        checked_at=NOW,
        message="  disconnected  ",
    )

    assert (
        snapshot.message
        == "disconnected"
    )


def test_empty_connectivity_message_rejected():
    with pytest.raises(
        ValueError,
        match=(
            "connectivity message "
            "cannot be empty"
        ),
    ):
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            connected=False,
            checked_at=NOW,
            message=" ",
        )


# ============================================================
# Initial monitor state
# ============================================================


def test_monitor_initially_unknown():
    monitor, _ = make_monitor()

    assert (
        monitor.latest_snapshot
        is None
    )

    assert (
        monitor.connectivity_known
        is False
    )

    assert monitor.connected is False

    assert (
        monitor.usable_for_new_entries
        is False
    )

    assert (
        monitor.requires_new_entry_block()
        is True
    )


def test_initial_failure_count_zero():
    monitor, _ = make_monitor()

    assert (
        monitor.consecutive_failures
        == 0
    )

    assert (
        monitor.last_failure
        is None
    )

    assert (
        monitor.last_success_at
        is None
    )


def test_monitor_preserves_identity():
    monitor, _ = make_monitor()

    assert (
        monitor.broker
        is BrokerType.DHAN
    )

    assert (
        monitor.account_id
        == ACCOUNT_ID
    )


# ============================================================
# Successful check
# ============================================================


def test_successful_connectivity_check():
    monitor, provider = (
        make_monitor()
    )

    snapshot = monitor.check(
        checked_at=NOW
    )

    assert snapshot.connected is True

    assert monitor.connected is True

    assert (
        monitor.connectivity_known
        is True
    )

    assert (
        monitor.usable_for_new_entries
        is True
    )

    assert (
        monitor.requires_new_entry_block()
        is False
    )

    assert (
        len(provider.calls)
        == 1
    )


def test_provider_receives_identity():
    monitor, provider = (
        make_monitor()
    )

    monitor.check(
        checked_at=NOW
    )

    (
        broker,
        account_id,
        checked_at,
    ) = provider.calls[0]

    assert broker is BrokerType.DHAN

    assert (
        account_id
        == ACCOUNT_ID
    )

    assert (
        checked_at
        == NOW
    )


def test_success_updates_last_success_time():
    monitor, _ = make_monitor()

    monitor.check(
        checked_at=NOW
    )

    assert (
        monitor.last_success_at
        == NOW
    )


def test_success_resets_failure_count():
    provider = FakeConnectivityProvider()

    monitor, _ = make_monitor(
        provider
    )

    provider.result = (
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            connected=False,
            checked_at=NOW,
            message="temporary disconnect",
        )
    )

    monitor.check(
        checked_at=NOW
    )

    assert (
        monitor.consecutive_failures
        == 1
    )

    provider.result = (
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            connected=True,
            checked_at=LATER,
        )
    )

    monitor.check(
        checked_at=LATER
    )

    assert (
        monitor.consecutive_failures
        == 0
    )

    assert (
        monitor.last_failure
        is None
    )

    assert (
        monitor.last_success_at
        == LATER
    )


# ============================================================
# Disconnected result
# ============================================================


def test_disconnected_snapshot_blocks_entries():
    provider = FakeConnectivityProvider()

    provider.result = (
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            connected=False,
            checked_at=NOW,
            message="broker disconnected",
        )
    )

    monitor, _ = make_monitor(
        provider
    )

    snapshot = monitor.check(
        checked_at=NOW
    )

    assert snapshot.connected is False

    assert monitor.connected is False

    assert (
        monitor.usable_for_new_entries
        is False
    )

    assert (
        monitor.requires_new_entry_block()
        is True
    )

    assert (
        monitor.last_failure
        == "broker disconnected"
    )


def test_disconnected_result_increments_failures():
    provider = FakeConnectivityProvider()

    provider.result = (
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            connected=False,
            checked_at=NOW,
        )
    )

    monitor, _ = make_monitor(
        provider
    )

    monitor.check(
        checked_at=NOW
    )

    assert (
        monitor.consecutive_failures
        == 1
    )

    monitor.check(
        checked_at=LATER
    )

    assert (
        monitor.consecutive_failures
        == 2
    )


# ============================================================
# Provider exception
# ============================================================


def test_provider_exception_becomes_connectivity_failure():
    provider = FakeConnectivityProvider()

    provider.error = RuntimeError(
        "broker API unavailable"
    )

    monitor, _ = make_monitor(
        provider
    )

    with pytest.raises(
        BrokerConnectivityCheckError,
        match=(
            "broker connectivity "
            "check failed"
        ),
    ):
        monitor.check(
            checked_at=NOW
        )

    assert monitor.connected is False

    assert (
        monitor.connectivity_known
        is True
    )

    assert (
        monitor.latest_snapshot
        is not None
    )

    assert (
        monitor.latest_snapshot.connected
        is False
    )

    assert (
        monitor.last_failure
        == "broker API unavailable"
    )

    assert (
        monitor.consecutive_failures
        == 1
    )


def test_repeated_provider_exceptions_accumulate_failures():
    provider = FakeConnectivityProvider()

    provider.error = RuntimeError(
        "network unavailable"
    )

    monitor, _ = make_monitor(
        provider
    )

    for checked_at in (
        NOW,
        LATER,
    ):
        with pytest.raises(
            BrokerConnectivityCheckError
        ):
            monitor.check(
                checked_at=checked_at
            )

    assert (
        monitor.consecutive_failures
        == 2
    )


# ============================================================
# Last-success semantics
# ============================================================


def test_failed_check_does_not_remove_last_success_time():
    provider = FakeConnectivityProvider()

    monitor, _ = make_monitor(
        provider
    )

    monitor.check(
        checked_at=NOW
    )

    assert (
        monitor.last_success_at
        == NOW
    )

    provider.error = RuntimeError(
        "temporary outage"
    )

    with pytest.raises(
        BrokerConnectivityCheckError
    ):
        monitor.check(
            checked_at=LATER
        )

    assert (
        monitor.last_success_at
        == NOW
    )

    assert monitor.connected is False


# ============================================================
# Identity validation
# ============================================================


def test_provider_account_mismatch_rejected():
    provider = FakeConnectivityProvider()

    provider.result = (
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=BrokerAccountId(
                "OTHER"
            ),
            connected=True,
            checked_at=NOW,
        )
    )

    monitor, _ = make_monitor(
        provider
    )

    with pytest.raises(
        BrokerConnectivityCheckError,
        match=(
            "returned mismatched account"
        ),
    ):
        monitor.check(
            checked_at=NOW
        )

    assert (
        monitor.last_failure
        == (
            "connectivity provider "
            "returned mismatched account"
        )
    )

    assert (
        monitor.consecutive_failures
        == 1
    )


# ============================================================
# Snapshot replacement
# ============================================================


def test_new_check_replaces_previous_snapshot():
    provider = FakeConnectivityProvider()

    monitor, _ = make_monitor(
        provider
    )

    first = monitor.check(
        checked_at=NOW
    )

    provider.result = (
        BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            connected=False,
            checked_at=LATER,
            message="disconnected",
        )
    )

    second = monitor.check(
        checked_at=LATER
    )

    assert second != first

    assert (
        monitor.latest_snapshot
        == second
    )

    assert monitor.connected is False