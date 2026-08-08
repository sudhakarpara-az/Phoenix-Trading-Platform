"""
Phoenix M09 Account Trading Eligibility Policy.

Combines broker/account state into one account-level
new-entry decision.

Inputs:
    - broker session state
    - account profile state
    - funds availability
    - broker connectivity state

Outputs:
    - AccountTradingEligibility

This policy does NOT evaluate:
    - M07 risk limits
    - M08 runtime state
    - M06 order eligibility
    - strategy/signal rules

Those remain independent safety gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.account.account_types import (
    AccountEligibilityReason,
    AccountProfile,
    AccountTradingEligibility,
    BrokerAccountId,
    BrokerAccountStatus,
    BrokerSessionSnapshot,
    BrokerSessionStatus,
    BrokerType,
)
from src.account.funds_provider import (
    AccountFundsService,
)


@dataclass(
    frozen=True,
    slots=True,
)
class BrokerConnectivitySnapshot:
    """
    Lightweight connectivity input for T05.

    T06 will replace this with a dedicated monitor/service
    while preserving the eligibility contract.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    connected: bool

    checked_at: datetime


class AccountTradingEligibilityPolicy:
    """
    Evaluates whether one broker account may accept a NEW ENTRY.

    Protective exits are intentionally outside this policy.
    """

    def evaluate(
        self,
        *,
        session: BrokerSessionSnapshot,
        profile: AccountProfile | None,
        funds: AccountFundsService,
        connectivity: BrokerConnectivitySnapshot,
        required_cash: Decimal,
        evaluated_at: datetime,
    ) -> AccountTradingEligibility:
        if required_cash < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        self._validate_identity(
            session=session,
            profile=profile,
            funds=funds,
            connectivity=connectivity,
        )

        broker = session.broker
        account_id = session.account_id

        # ====================================================
        # Connectivity
        # ====================================================

        if not connectivity.connected:
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .BROKER_UNAVAILABLE
                ),
                evaluated_at=evaluated_at,
                message=(
                    "broker connectivity unavailable"
                ),
                required_cash=required_cash,
            )

        # ====================================================
        # Session
        # ====================================================

        if (
            session.status
            is BrokerSessionStatus.EXPIRED
        ):
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .SESSION_EXPIRED
                ),
                evaluated_at=evaluated_at,
                message=(
                    "broker session expired"
                ),
                required_cash=required_cash,
            )

        if (
            session.status
            is BrokerSessionStatus.FAILED
        ):
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .SESSION_FAILED
                ),
                evaluated_at=evaluated_at,
                message=(
                    session.failure_message
                    or "broker session failed"
                ),
                required_cash=required_cash,
            )

        if (
            session.status
            is not BrokerSessionStatus.AUTHENTICATED
        ):
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .SESSION_NOT_AUTHENTICATED
                ),
                evaluated_at=evaluated_at,
                message=(
                    "broker session is not authenticated"
                ),
                required_cash=required_cash,
            )

        # ====================================================
        # Profile
        # ====================================================

        if profile is None:
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .PROFILE_UNAVAILABLE
                ),
                evaluated_at=evaluated_at,
                message=(
                    "account profile unavailable"
                ),
                required_cash=required_cash,
            )

        if (
            profile.account_status
            is BrokerAccountStatus.UNKNOWN
        ):
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .ACCOUNT_STATUS_UNKNOWN
                ),
                evaluated_at=evaluated_at,
                message=(
                    "account status unknown"
                ),
                required_cash=required_cash,
            )

        if (
            profile.account_status
            is BrokerAccountStatus.BLOCKED
        ):
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .ACCOUNT_BLOCKED
                ),
                evaluated_at=evaluated_at,
                message=(
                    "broker account is blocked"
                ),
                required_cash=required_cash,
            )

        if (
            profile.account_status
            is BrokerAccountStatus.INACTIVE
        ):
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .ACCOUNT_INACTIVE
                ),
                evaluated_at=evaluated_at,
                message=(
                    "broker account is inactive"
                ),
                required_cash=required_cash,
            )

        if not profile.trading_enabled:
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .TRADING_NOT_ENABLED
                ),
                evaluated_at=evaluated_at,
                message=(
                    "trading is not enabled "
                    "for broker account"
                ),
                required_cash=required_cash,
            )

        # ====================================================
        # Funds
        # ====================================================

        if not funds.funds_available:
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .FUNDS_UNAVAILABLE
                ),
                evaluated_at=evaluated_at,
                message=(
                    "broker funds snapshot unavailable"
                ),
                required_cash=required_cash,
            )

        available_cash = (
            funds.available_cash
        )

        if available_cash is None:
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .FUNDS_UNAVAILABLE
                ),
                evaluated_at=evaluated_at,
                message=(
                    "available cash unavailable"
                ),
                required_cash=required_cash,
            )

        if available_cash < required_cash:
            return AccountTradingEligibility.block(
                broker=broker,
                account_id=account_id,
                reason=(
                    AccountEligibilityReason
                    .INSUFFICIENT_FUNDS
                ),
                evaluated_at=evaluated_at,
                message=(
                    "insufficient available cash"
                ),
                available_cash=available_cash,
                required_cash=required_cash,
            )

        return AccountTradingEligibility.allow(
            broker=broker,
            account_id=account_id,
            evaluated_at=evaluated_at,
            available_cash=available_cash,
            required_cash=required_cash,
        )

    # ========================================================
    # Identity consistency
    # ========================================================

    @staticmethod
    def _validate_identity(
        *,
        session: BrokerSessionSnapshot,
        profile: AccountProfile | None,
        funds: AccountFundsService,
        connectivity: BrokerConnectivitySnapshot,
    ) -> None:
        broker = session.broker
        account_id = session.account_id

        if connectivity.broker is not broker:
            raise ValueError(
                "connectivity broker does not "
                "match session broker"
            )

        if (
            connectivity.account_id
            != account_id
        ):
            raise ValueError(
                "connectivity account does not "
                "match session account"
            )

        if funds.broker is not broker:
            raise ValueError(
                "funds broker does not "
                "match session broker"
            )

        if (
            funds.account_id
            != account_id
        ):
            raise ValueError(
                "funds account does not "
                "match session account"
            )

        if profile is not None:
            if profile.broker is not broker:
                raise ValueError(
                    "profile broker does not "
                    "match session broker"
                )

            if (
                profile.account_id
                != account_id
            ):
                raise ValueError(
                    "profile account does not "
                    "match session account"
                )