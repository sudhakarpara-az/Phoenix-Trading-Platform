"""
Phoenix M13 passive account/operator read surface.

This module reads already-persisted M09 account facts only.

It deliberately does not:

- authenticate or re-authenticate;
- call Dhan;
- refresh account/profile/funds/connectivity;
- evaluate account eligibility;
- mutate the account registry;
- write persistence;
- expose credentials or authentication tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


# ============================================================
# Transport-neutral immutable views
# ============================================================


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorAccountProfileView:
    account_status: str
    client_name: str | None
    trading_enabled: bool
    product_type: str | None

    profile_fetched_at: datetime | None
    updated_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorSessionView:
    status: str

    authenticated_at: datetime | None
    expires_at: datetime | None
    updated_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorFundsView:
    available_cash: Decimal
    available_margin: Decimal
    utilized_margin: Decimal
    collateral: Decimal
    opening_balance: Decimal | None

    fetched_at: datetime


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorConnectivityView:
    connected: bool
    checked_at: datetime
    latency_ms: float | None


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorHealthView:
    status: str
    checked_at: datetime

    broker_connected: bool
    session_authenticated: bool
    profile_available: bool
    funds_available: bool


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorEligibilityView:
    status: str
    reason: str

    evaluated_at: datetime

    available_cash: Decimal | None
    required_cash: Decimal | None


@dataclass(
    frozen=True,
    slots=True,
)
class OperatorAccountView:
    broker: str
    account_id: str

    profile: OperatorAccountProfileView | None
    session: OperatorSessionView | None
    funds: OperatorFundsView | None
    connectivity: OperatorConnectivityView | None
    health: OperatorHealthView | None
    eligibility: OperatorEligibilityView | None

    captured_at: datetime


# ============================================================
# Narrow structural repository read ports
# ============================================================


class BrokerAccountReader(
    Protocol,
):
    def get(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> Any | None:
        ...


class LatestAccountReader(
    Protocol,
):
    def latest_for_account(
        self,
        *,
        broker: str,
        account_id: str,
    ) -> Any | None:
        ...


# ============================================================
# Passive service
# ============================================================


class OperatorAccountService:
    """
    Read one passive M09 operator snapshot from durable state.

    Each durable source is queried once per capture.
    """

    def __init__(
        self,
        *,
        broker: str,
        account_id: str,
        account_repository: BrokerAccountReader,
        session_repository: LatestAccountReader,
        fund_repository: LatestAccountReader,
        connectivity_repository: LatestAccountReader,
        health_repository: LatestAccountReader,
        eligibility_repository: LatestAccountReader,
    ) -> None:
        resolved_broker = broker.strip()
        resolved_account_id = account_id.strip()

        if not resolved_broker:
            raise ValueError(
                "broker cannot be empty"
            )

        if not resolved_account_id:
            raise ValueError(
                "account_id cannot be empty"
            )

        self._broker = resolved_broker
        self._account_id = resolved_account_id

        self._account_repository = account_repository
        self._session_repository = session_repository
        self._fund_repository = fund_repository
        self._connectivity_repository = (
            connectivity_repository
        )
        self._health_repository = health_repository
        self._eligibility_repository = (
            eligibility_repository
        )

    @property
    def broker(
        self,
    ) -> str:
        return self._broker

    @property
    def account_id(
        self,
    ) -> str:
        return self._account_id

    @property
    def account_repository(
        self,
    ) -> BrokerAccountReader:
        return self._account_repository

    @property
    def session_repository(
        self,
    ) -> LatestAccountReader:
        return self._session_repository

    @property
    def fund_repository(
        self,
    ) -> LatestAccountReader:
        return self._fund_repository

    @property
    def connectivity_repository(
        self,
    ) -> LatestAccountReader:
        return self._connectivity_repository

    @property
    def health_repository(
        self,
    ) -> LatestAccountReader:
        return self._health_repository

    @property
    def eligibility_repository(
        self,
    ) -> LatestAccountReader:
        return self._eligibility_repository

    def capture(
        self,
        *,
        captured_at: datetime,
    ) -> OperatorAccountView:
        if type(captured_at) is not datetime:
            raise TypeError(
                "captured_at must be datetime"
            )

        broker = self._broker
        account_id = self._account_id

        # Every durable source is read exactly once.
        profile_record = (
            self._account_repository.get(
                broker=broker,
                account_id=account_id,
            )
        )

        session_record = (
            self._session_repository
            .latest_for_account(
                broker=broker,
                account_id=account_id,
            )
        )

        fund_record = (
            self._fund_repository
            .latest_for_account(
                broker=broker,
                account_id=account_id,
            )
        )

        connectivity_record = (
            self._connectivity_repository
            .latest_for_account(
                broker=broker,
                account_id=account_id,
            )
        )

        health_record = (
            self._health_repository
            .latest_for_account(
                broker=broker,
                account_id=account_id,
            )
        )

        eligibility_record = (
            self._eligibility_repository
            .latest_for_account(
                broker=broker,
                account_id=account_id,
            )
        )

        return OperatorAccountView(
            broker=broker,
            account_id=account_id,
            profile=(
                None
                if profile_record is None
                else OperatorAccountProfileView(
                    account_status=(
                        profile_record.account_status
                    ),
                    client_name=(
                        profile_record.client_name
                    ),
                    trading_enabled=(
                        profile_record.trading_enabled
                    ),
                    product_type=(
                        profile_record.product_type
                    ),
                    profile_fetched_at=(
                        profile_record
                        .profile_fetched_at
                    ),
                    updated_at=(
                        profile_record.updated_at
                    ),
                )
            ),
            session=(
                None
                if session_record is None
                else OperatorSessionView(
                    status=session_record.status,
                    authenticated_at=(
                        session_record.authenticated_at
                    ),
                    expires_at=(
                        session_record.expires_at
                    ),
                    updated_at=(
                        session_record.updated_at
                    ),
                )
            ),
            funds=(
                None
                if fund_record is None
                else OperatorFundsView(
                    available_cash=(
                        fund_record.available_cash
                    ),
                    available_margin=(
                        fund_record.available_margin
                    ),
                    utilized_margin=(
                        fund_record.utilized_margin
                    ),
                    collateral=(
                        fund_record.collateral
                    ),
                    opening_balance=(
                        fund_record.opening_balance
                    ),
                    fetched_at=(
                        fund_record.fetched_at
                    ),
                )
            ),
            connectivity=(
                None
                if connectivity_record is None
                else OperatorConnectivityView(
                    connected=(
                        connectivity_record.connected
                    ),
                    checked_at=(
                        connectivity_record.checked_at
                    ),
                    latency_ms=(
                        connectivity_record.latency_ms
                    ),
                )
            ),
            health=(
                None
                if health_record is None
                else OperatorHealthView(
                    status=health_record.status,
                    checked_at=(
                        health_record.checked_at
                    ),
                    broker_connected=(
                        health_record.broker_connected
                    ),
                    session_authenticated=(
                        health_record
                        .session_authenticated
                    ),
                    profile_available=(
                        health_record.profile_available
                    ),
                    funds_available=(
                        health_record.funds_available
                    ),
                )
            ),
            eligibility=(
                None
                if eligibility_record is None
                else OperatorEligibilityView(
                    status=(
                        eligibility_record.status
                    ),
                    reason=(
                        eligibility_record.reason
                    ),
                    evaluated_at=(
                        eligibility_record.evaluated_at
                    ),
                    available_cash=(
                        eligibility_record
                        .available_cash
                    ),
                    required_cash=(
                        eligibility_record
                        .required_cash
                    ),
                )
            ),
            captured_at=captured_at,
        )


__all__ = [
    "BrokerAccountReader",
    "LatestAccountReader",
    "OperatorAccountProfileView",
    "OperatorAccountService",
    "OperatorAccountView",
    "OperatorConnectivityView",
    "OperatorEligibilityView",
    "OperatorFundsView",
    "OperatorHealthView",
    "OperatorSessionView",
]
