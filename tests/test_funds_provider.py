"""
Phoenix M09-T04 Funds & Margin Snapshot tests.
"""

from datetime import (
    datetime,
    timedelta,
)
from decimal import Decimal

import pytest

from src.account.account_types import (
    AccountFundsSnapshot,
    BrokerAccountId,
    BrokerType,
)
from src.account.funds_provider import (
    AccountFundsFetchError,
    AccountFundsService,
)


NOW = datetime(
    2026,
    8,
    8,
    9,
    35,
)

LATER = (
    NOW
    + timedelta(minutes=5)
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)


class FakeFundsProvider:
    def __init__(
        self,
    ) -> None:
        self.calls = []

        self.result = AccountFundsSnapshot(
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
            collateral=Decimal(
                "5000"
            ),
            opening_balance=Decimal(
                "110000"
            ),
            fetched_at=NOW,
        )

        self.error = None

    def fetch_funds(
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
        or FakeFundsProvider()
    )

    service = AccountFundsService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        provider=provider,
    )

    return service, provider


# ============================================================
# Initial state
# ============================================================


def test_funds_initially_unavailable():
    service, _ = make_service()

    assert (
        service.latest_snapshot
        is None
    )

    assert (
        service.funds_available
        is False
    )

    assert (
        service.last_failure
        is None
    )


def test_initial_available_cash_is_none():
    service, _ = make_service()

    assert (
        service.available_cash
        is None
    )


def test_initial_available_margin_is_none():
    service, _ = make_service()

    assert (
        service.available_margin
        is None
    )


def test_initial_utilized_margin_is_none():
    service, _ = make_service()

    assert (
        service.utilized_margin
        is None
    )


def test_no_snapshot_blocks_new_entry():
    service, _ = make_service()

    assert (
        service.requires_new_entry_block(
            required_cash=Decimal(
                "1000"
            )
        )
        is True
    )


# ============================================================
# Identity
# ============================================================


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


def test_refresh_funds_success():
    service, provider = (
        make_service()
    )

    snapshot = service.refresh(
        requested_at=NOW
    )

    assert (
        snapshot.available_cash
        == Decimal("100000")
    )

    assert (
        service.latest_snapshot
        == snapshot
    )

    assert (
        service.funds_available
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


def test_provider_receives_identity():
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

    assert (
        broker
        is BrokerType.DHAN
    )

    assert (
        account_id
        == ACCOUNT_ID
    )

    assert (
        requested_at
        == NOW
    )


def test_refreshed_cash_properties():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.available_cash
        == Decimal("100000")
    )

    assert (
        service.available_margin
        == Decimal("25000")
    )

    assert (
        service.utilized_margin
        == Decimal("10000")
    )


# ============================================================
# Available cash
# ============================================================


def test_available_cash_is_sufficient():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.has_available_cash(
            Decimal("50000")
        )
        is True
    )


def test_exact_available_cash_is_sufficient():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.has_available_cash(
            Decimal("100000")
        )
        is True
    )


def test_cash_above_available_is_insufficient():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.has_available_cash(
            Decimal("100001")
        )
        is False
    )


def test_no_snapshot_has_no_available_cash():
    service, _ = make_service()

    assert (
        service.has_available_cash(
            Decimal("1")
        )
        is False
    )


def test_zero_required_cash_is_allowed_when_snapshot_exists():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.has_available_cash(
            Decimal("0")
        )
        is True
    )


def test_negative_required_cash_rejected():
    service, _ = make_service()

    with pytest.raises(
        ValueError,
        match=(
            "required cash cannot be negative"
        ),
    ):
        service.has_available_cash(
            Decimal("-1")
        )


# ============================================================
# Shortfall
# ============================================================


def test_cash_shortfall_when_insufficient():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    shortfall = (
        service.cash_shortfall(
            Decimal("125000")
        )
    )

    assert (
        shortfall
        == Decimal("25000")
    )


def test_cash_shortfall_zero_when_sufficient():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.cash_shortfall(
            Decimal("50000")
        )
        == Decimal("0")
    )


def test_cash_shortfall_none_without_snapshot():
    service, _ = make_service()

    assert (
        service.cash_shortfall(
            Decimal("50000")
        )
        is None
    )


def test_cash_shortfall_negative_required_rejected():
    service, _ = make_service()

    with pytest.raises(
        ValueError,
        match=(
            "required cash cannot be negative"
        ),
    ):
        service.cash_shortfall(
            Decimal("-1")
        )


# ============================================================
# New-entry funds gate
# ============================================================


def test_sufficient_cash_does_not_block_entry():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.requires_new_entry_block(
            required_cash=Decimal(
                "6500"
            )
        )
        is False
    )


def test_insufficient_cash_blocks_entry():
    service, _ = make_service()

    service.refresh(
        requested_at=NOW
    )

    assert (
        service.requires_new_entry_block(
            required_cash=Decimal(
                "150000"
            )
        )
        is True
    )


def test_negative_entry_requirement_rejected():
    service, _ = make_service()

    with pytest.raises(
        ValueError,
        match=(
            "required cash cannot be negative"
        ),
    ):
        service.requires_new_entry_block(
            required_cash=Decimal(
                "-1"
            )
        )


# ============================================================
# Failure handling
# ============================================================


def test_provider_failure_raises_funds_error():
    provider = FakeFundsProvider()

    provider.error = RuntimeError(
        "funds endpoint unavailable"
    )

    service, _ = make_service(
        provider
    )

    with pytest.raises(
        AccountFundsFetchError,
        match=(
            "account funds fetch failed"
        ),
    ):
        service.refresh(
            requested_at=NOW
        )

    assert (
        service.last_failure
        == "funds endpoint unavailable"
    )


def test_first_fetch_failure_keeps_snapshot_unavailable():
    provider = FakeFundsProvider()

    provider.error = RuntimeError(
        "broker unavailable"
    )

    service, _ = make_service(
        provider
    )

    with pytest.raises(
        AccountFundsFetchError
    ):
        service.refresh(
            requested_at=NOW
        )

    assert (
        service.latest_snapshot
        is None
    )

    assert (
        service.funds_available
        is False
    )

    assert (
        service.requires_new_entry_block(
            required_cash=Decimal(
                "1000"
            )
        )
        is True
    )


def test_failed_refresh_retains_last_good_snapshot():
    provider = FakeFundsProvider()

    service, _ = make_service(
        provider
    )

    first = service.refresh(
        requested_at=NOW
    )

    provider.error = RuntimeError(
        "temporary funds failure"
    )

    with pytest.raises(
        AccountFundsFetchError
    ):
        service.refresh(
            requested_at=LATER
        )

    assert (
        service.latest_snapshot
        == first
    )

    assert (
        service.last_failure
        == "temporary funds failure"
    )


def test_successful_refresh_clears_previous_failure():
    provider = FakeFundsProvider()

    service, _ = make_service(
        provider
    )

    provider.error = RuntimeError(
        "temporary failure"
    )

    with pytest.raises(
        AccountFundsFetchError
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
# Provider validation
# ============================================================


def test_provider_account_mismatch_rejected():
    provider = FakeFundsProvider()

    provider.result = AccountFundsSnapshot(
        broker=BrokerType.DHAN,
        account_id=BrokerAccountId(
            "OTHER-ACCOUNT"
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

    service, _ = make_service(
        provider
    )

    with pytest.raises(
        AccountFundsFetchError,
        match=(
            "returned mismatched account"
        ),
    ):
        service.refresh(
            requested_at=NOW
        )

    assert (
        service.latest_snapshot
        is None
    )

    assert (
        service.last_failure
        == (
            "account funds provider "
            "returned mismatched account"
        )
    )


# ============================================================
# Snapshot replacement
# ============================================================


def test_new_successful_snapshot_replaces_previous_snapshot():
    provider = FakeFundsProvider()

    service, _ = make_service(
        provider
    )

    first = service.refresh(
        requested_at=NOW
    )

    provider.result = AccountFundsSnapshot(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        available_cash=Decimal(
            "75000"
        ),
        available_margin=Decimal(
            "10000"
        ),
        utilized_margin=Decimal(
            "20000"
        ),
        collateral=Decimal(
            "0"
        ),
        fetched_at=LATER,
    )

    second = service.refresh(
        requested_at=LATER
    )

    assert second != first

    assert (
        service.latest_snapshot
        == second
    )

    assert (
        service.available_cash
        == Decimal("75000")
    )


# ============================================================
# Margin state
# ============================================================


def test_margin_values_are_preserved():
    service, _ = make_service()

    snapshot = service.refresh(
        requested_at=NOW
    )

    assert (
        snapshot.available_margin
        == Decimal("25000")
    )

    assert (
        snapshot.utilized_margin
        == Decimal("10000")
    )

    assert (
        snapshot.collateral
        == Decimal("5000")
    )

    assert (
        snapshot.opening_balance
        == Decimal("110000")
    )