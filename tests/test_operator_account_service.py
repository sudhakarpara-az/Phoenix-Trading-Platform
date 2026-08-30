from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pytest

from src.api.operator_account import (
    OperatorAccountService,
)


CAPTURED = datetime(
    2026,
    8,
    10,
    14,
    30,
)

PROFILE_TIME = datetime(
    2026,
    8,
    10,
    9,
    10,
)

SESSION_TIME = datetime(
    2026,
    8,
    10,
    9,
    12,
)

FUNDS_TIME = datetime(
    2026,
    8,
    10,
    9,
    16,
)

CHECKED_TIME = datetime(
    2026,
    8,
    10,
    14,
    20,
)

ELIGIBILITY_TIME = datetime(
    2026,
    8,
    10,
    14,
    25,
)


@dataclass(
    frozen=True,
    slots=True,
)
class ProfileRecord:
    account_status: str = "ACTIVE"
    client_name: str | None = "Phoenix Trader"
    trading_enabled: bool = True
    product_type: str | None = "OPTIONS"
    profile_fetched_at: datetime | None = PROFILE_TIME
    updated_at: datetime = PROFILE_TIME


@dataclass(
    frozen=True,
    slots=True,
)
class SessionRecord:
    status: str = "AUTHENTICATED"
    authenticated_at: datetime | None = SESSION_TIME
    expires_at: datetime | None = None
    updated_at: datetime = SESSION_TIME


@dataclass(
    frozen=True,
    slots=True,
)
class FundRecord:
    available_cash: Decimal = Decimal("100000.00")
    available_margin: Decimal = Decimal("100000.00")
    utilized_margin: Decimal = Decimal("0.00")
    collateral: Decimal = Decimal("0.00")
    opening_balance: Decimal | None = Decimal("100000.00")
    fetched_at: datetime = FUNDS_TIME


@dataclass(
    frozen=True,
    slots=True,
)
class ConnectivityRecord:
    connected: bool = True
    checked_at: datetime = CHECKED_TIME
    latency_ms: float | None = 25.5


@dataclass(
    frozen=True,
    slots=True,
)
class HealthRecord:
    status: str = "HEALTHY"
    checked_at: datetime = CHECKED_TIME
    broker_connected: bool = True
    session_authenticated: bool = True
    profile_available: bool = True
    funds_available: bool = True


@dataclass(
    frozen=True,
    slots=True,
)
class EligibilityRecord:
    status: str = "ALLOWED"
    reason: str = "ELIGIBLE"
    evaluated_at: datetime = ELIGIBILITY_TIME
    available_cash: Decimal | None = Decimal("100000.00")
    required_cash: Decimal | None = Decimal("10000.00")


class FakeAccountRepository:
    def __init__(
        self,
        value,
    ) -> None:
        self.value = value
        self.calls = []

    def get(
        self,
        *,
        broker: str,
        account_id: str,
    ):
        self.calls.append(
            (
                broker,
                account_id,
            )
        )
        return self.value


class FakeLatestRepository:
    def __init__(
        self,
        value,
    ) -> None:
        self.value = value
        self.calls = []

    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ):
        self.calls.append(
            (
                broker,
                account_id,
            )
        )
        return self.value


def make_service(
    *,
    populated: bool = True,
):
    profile = FakeAccountRepository(
        ProfileRecord()
        if populated
        else None
    )

    session = FakeLatestRepository(
        SessionRecord()
        if populated
        else None
    )

    funds = FakeLatestRepository(
        FundRecord()
        if populated
        else None
    )

    connectivity = FakeLatestRepository(
        ConnectivityRecord()
        if populated
        else None
    )

    health = FakeLatestRepository(
        HealthRecord()
        if populated
        else None
    )

    eligibility = FakeLatestRepository(
        EligibilityRecord()
        if populated
        else None
    )

    service = OperatorAccountService(
        broker="DHAN",
        account_id="DHAN-001",
        account_repository=profile,
        session_repository=session,
        fund_repository=funds,
        connectivity_repository=connectivity,
        health_repository=health,
        eligibility_repository=eligibility,
    )

    return (
        service,
        profile,
        session,
        funds,
        connectivity,
        health,
        eligibility,
    )


def test_populated_account_snapshot():
    (
        service,
        _,
        _,
        _,
        _,
        _,
        _,
    ) = make_service()

    result = service.capture(
        captured_at=CAPTURED
    )

    assert result.broker == "DHAN"
    assert result.account_id == "DHAN-001"

    assert result.profile is not None
    assert result.profile.account_status == "ACTIVE"
    assert result.profile.trading_enabled is True

    assert result.session is not None
    assert result.session.status == "AUTHENTICATED"

    assert result.funds is not None
    assert (
        result.funds.available_cash
        == Decimal("100000.00")
    )

    assert result.connectivity is not None
    assert result.connectivity.connected is True

    assert result.health is not None
    assert result.health.status == "HEALTHY"

    assert result.eligibility is not None
    assert result.eligibility.status == "ALLOWED"
    assert result.eligibility.reason == "ELIGIBLE"

    assert result.captured_at == CAPTURED


def test_missing_durable_state_is_exposed_as_none():
    (
        service,
        _,
        _,
        _,
        _,
        _,
        _,
    ) = make_service(
        populated=False
    )

    result = service.capture(
        captured_at=CAPTURED
    )

    assert result.profile is None
    assert result.session is None
    assert result.funds is None
    assert result.connectivity is None
    assert result.health is None
    assert result.eligibility is None


def test_every_repository_is_read_exactly_once():
    (
        service,
        profile,
        session,
        funds,
        connectivity,
        health,
        eligibility,
    ) = make_service()

    service.capture(
        captured_at=CAPTURED
    )

    expected = [
        (
            "DHAN",
            "DHAN-001",
        )
    ]

    assert profile.calls == expected
    assert session.calls == expected
    assert funds.calls == expected
    assert connectivity.calls == expected
    assert health.calls == expected
    assert eligibility.calls == expected


def test_invalid_capture_time_is_rejected_before_reads():
    (
        service,
        profile,
        session,
        funds,
        connectivity,
        health,
        eligibility,
    ) = make_service()

    with pytest.raises(
        TypeError,
        match="captured_at must be datetime",
    ):
        service.capture(
            captured_at=None,  # type: ignore[arg-type]
        )

    assert profile.calls == []
    assert session.calls == []
    assert funds.calls == []
    assert connectivity.calls == []
    assert health.calls == []
    assert eligibility.calls == []


def test_identity_is_normalized_at_construction():
    (
        service,
        _,
        _,
        _,
        _,
        _,
        _,
    ) = make_service()

    assert service.broker == "DHAN"
    assert service.account_id == "DHAN-001"
