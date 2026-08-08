"""
Phoenix M09-T10 Dhan Account Adapter tests.

No live Dhan request is made.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.account.account_types import (
    BrokerAccountId,
    BrokerAccountStatus,
    BrokerType,
)
from src.account.dhan_account_adapter import (
    DhanAccountAdapter,
    DhanAccountAdapterError,
)


NOW = datetime(
    2026,
    8,
    8,
    11,
    30,
)

ACCOUNT_ID = BrokerAccountId(
    "1100003626"
)


class FakeDhanClient:
    def __init__(
        self,
    ) -> None:
        self.fund_calls = 0

        self.fund_response = {
            "dhanClientId":
                ACCOUNT_ID.value,

            "availabelBalance":
                98440.0,

            "sodLimit":
                113642.0,

            "collateralAmount":
                5000.0,

            "receiveableAmount":
                0.0,

            "utilizedAmount":
                15202.0,

            "blockedPayoutAmount":
                0.0,

            "withdrawableBalance":
                98310.0,
        }

        self.fund_error = None

    def get_fund_limits(
        self,
    ):
        self.fund_calls += 1

        if self.fund_error is not None:
            raise self.fund_error

        return self.fund_response


class FakeProfileFetcher:
    def __init__(
        self,
    ) -> None:
        self.calls = 0

        self.response = {
            "dhanClientId":
                ACCOUNT_ID.value,

            "tokenValidity":
                "08/08/2026 23:59",

            "activeSegment":
                (
                    "Equity, Derivative, "
                    "Currency"
                ),

            "ddpi": "Active",
            "mtf": "Deactive",
            "dataPlan": "Active",
            "dataValidity":
                "2026-08-08 23:59:00.0",
        }

        self.error = None

    def __call__(
        self,
    ):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return self.response


def make_adapter():
    client = FakeDhanClient()
    profile = FakeProfileFetcher()

    adapter = DhanAccountAdapter(
        dhan_client=client,
        profile_fetcher=profile,
        account_id=ACCOUNT_ID,
    )

    return (
        adapter,
        client,
        profile,
    )


# ============================================================
# Identity
# ============================================================


def test_adapter_identity():
    adapter, _, _ = (
        make_adapter()
    )

    assert (
        adapter.broker
        is BrokerType.DHAN
    )

    assert (
        adapter.account_id
        == ACCOUNT_ID
    )


# ============================================================
# Profile
# ============================================================


def test_fetch_profile():
    adapter, _, profile_fetcher = (
        make_adapter()
    )

    profile = adapter.fetch_profile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        requested_at=NOW,
    )

    assert (
        profile.account_id
        == ACCOUNT_ID
    )

    assert (
        profile.account_status
        is BrokerAccountStatus.ACTIVE
    )

    assert (
        profile.trading_enabled
        is True
    )

    assert (
        profile.product_type
        == (
            "Equity, Derivative, "
            "Currency"
        )
    )

    assert (
        profile.fetched_at
        == NOW
    )

    assert (
        profile_fetcher.calls
        == 1
    )


def test_profile_without_derivative_segment_disables_trading():
    adapter, _, profile_fetcher = (
        make_adapter()
    )

    profile_fetcher.response[
        "activeSegment"
    ] = "Equity, Currency"

    result = adapter.fetch_profile(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        requested_at=NOW,
    )

    assert (
        result.trading_enabled
        is False
    )


def test_profile_account_mismatch_rejected():
    adapter, _, profile_fetcher = (
        make_adapter()
    )

    profile_fetcher.response[
        "dhanClientId"
    ] = "OTHER"

    with pytest.raises(
        DhanAccountAdapterError,
        match=(
            "response account does not match"
        ),
    ):
        adapter.fetch_profile(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


def test_profile_fetch_exception_wrapped():
    adapter, _, profile_fetcher = (
        make_adapter()
    )

    profile_fetcher.error = RuntimeError(
        "profile unavailable"
    )

    with pytest.raises(
        DhanAccountAdapterError,
        match=(
            "user profile request failed"
        ),
    ):
        adapter.fetch_profile(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


# ============================================================
# Funds
# ============================================================


def test_fetch_funds():
    adapter, client, _ = (
        make_adapter()
    )

    funds = adapter.fetch_funds(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        requested_at=NOW,
    )

    assert (
        funds.available_cash
        == Decimal("98440.0")
    )

    assert (
        funds.available_margin
        == Decimal("0")
    )

    assert (
        funds.utilized_margin
        == Decimal("15202.0")
    )

    assert (
        funds.collateral
        == Decimal("5000.0")
    )

    assert (
        funds.opening_balance
        == Decimal("113642.0")
    )

    assert client.fund_calls == 1


def test_dhan_available_balance_spelling_is_supported():
    adapter, client, _ = (
        make_adapter()
    )

    assert (
        "availabelBalance"
        in client.fund_response
    )

    funds = adapter.fetch_funds(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        requested_at=NOW,
    )

    assert (
        funds.available_cash
        == Decimal("98440.0")
    )


def test_fund_account_mismatch_rejected():
    adapter, client, _ = (
        make_adapter()
    )

    client.fund_response[
        "dhanClientId"
    ] = "OTHER"

    with pytest.raises(
        DhanAccountAdapterError,
        match=(
            "response account does not match"
        ),
    ):
        adapter.fetch_funds(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


def test_missing_available_balance_rejected():
    adapter, client, _ = (
        make_adapter()
    )

    del client.fund_response[
        "availabelBalance"
    ]

    with pytest.raises(
        DhanAccountAdapterError,
        match=(
            "missing availabelBalance"
        ),
    ):
        adapter.fetch_funds(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


def test_negative_dhan_fund_value_rejected():
    adapter, client, _ = (
        make_adapter()
    )

    client.fund_response[
        "utilizedAmount"
    ] = -1

    with pytest.raises(
        DhanAccountAdapterError,
        match=(
            "negative utilizedAmount"
        ),
    ):
        adapter.fetch_funds(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


def test_fund_api_exception_wrapped():
    adapter, client, _ = (
        make_adapter()
    )

    client.fund_error = RuntimeError(
        "fund endpoint unavailable"
    )

    with pytest.raises(
        DhanAccountAdapterError,
        match=(
            "fund-limit request failed"
        ),
    ):
        adapter.fetch_funds(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


# ============================================================
# SDK envelope
# ============================================================


def test_sdk_data_envelope_supported():
    adapter, client, _ = (
        make_adapter()
    )

    client.fund_response = {
        "status": "success",
        "data": {
            "dhanClientId":
                ACCOUNT_ID.value,

            "availabelBalance": 50000,
            "sodLimit": 60000,
            "collateralAmount": 0,
            "utilizedAmount": 10000,
        },
    }

    funds = adapter.fetch_funds(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        requested_at=NOW,
    )

    assert (
        funds.available_cash
        == Decimal("50000")
    )


def test_error_envelope_rejected():
    adapter, client, _ = (
        make_adapter()
    )

    client.fund_response = {
        "errorCode": "DH-901",
        "errorMessage":
            "Invalid Authentication",
    }

    with pytest.raises(
        DhanAccountAdapterError,
        match="Invalid Authentication",
    ):
        adapter.fetch_funds(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


# ============================================================
# Connectivity
# ============================================================


def test_connectivity_success():
    adapter, _, _ = (
        make_adapter()
    )

    result = (
        adapter.check_connectivity(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            checked_at=NOW,
        )
    )

    assert result.connected is True


def test_connectivity_failure_returns_disconnected():
    adapter, _, profile_fetcher = (
        make_adapter()
    )

    profile_fetcher.error = (
        RuntimeError(
            "network unavailable"
        )
    )

    result = (
        adapter.check_connectivity(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            checked_at=NOW,
        )
    )

    assert (
        result.connected
        is False
    )

    assert (
        "network unavailable"
        in result.message
    )


def test_connectivity_account_mismatch_is_disconnected():
    adapter, _, profile_fetcher = (
        make_adapter()
    )

    profile_fetcher.response[
        "dhanClientId"
    ] = "OTHER"

    result = (
        adapter.check_connectivity(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            checked_at=NOW,
        )
    )

    assert (
        result.connected
        is False
    )


# ============================================================
# Requested identity
# ============================================================


def test_requested_account_mismatch_rejected():
    adapter, _, _ = (
        make_adapter()
    )

    with pytest.raises(
        DhanAccountAdapterError,
        match=(
            "requested account does not match"
        ),
    ):
        adapter.fetch_funds(
            broker=BrokerType.DHAN,
            account_id=BrokerAccountId(
                "OTHER"
            ),
            requested_at=NOW,
        )