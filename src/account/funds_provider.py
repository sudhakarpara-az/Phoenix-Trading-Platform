"""
Phoenix M09 Funds & Margin Provider boundary and service.

Responsibilities:
    - fetch broker funds/margin state through a provider boundary
    - validate broker/account identity
    - retain the latest successfully fetched funds snapshot
    - expose conservative funds availability state
    - provide cash-availability helpers

This module does NOT:
    - authenticate broker sessions
    - fetch account profile
    - decide complete account trading eligibility
    - place orders
    - persist funds snapshots
    - call Dhan directly

Dhan-specific funds mapping belongs to M09-T10.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from threading import RLock
from typing import Protocol

from src.account.account_types import (
    AccountFundsSnapshot,
    BrokerAccountId,
    BrokerType,
)


class AccountFundsProvider(
    Protocol,
):
    """
    Broker-independent funds/margin source.

    Concrete Dhan implementation will be introduced later.
    """

    def fetch_funds(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        requested_at: datetime,
    ) -> AccountFundsSnapshot:
        ...


class AccountFundsFetchError(
    RuntimeError
):
    """
    Account funds retrieval or validation failed.
    """


class AccountFundsService:
    """
    Owns the latest validated funds snapshot for one
    broker account.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        provider: AccountFundsProvider,
    ) -> None:
        self._broker = broker

        self._account_id = account_id

        self._provider = provider

        self._latest_snapshot: (
            AccountFundsSnapshot
            | None
        ) = None

        self._last_failure: (
            str
            | None
        ) = None

        self._lock = RLock()

    # ========================================================
    # Identity
    # ========================================================

    @property
    def broker(
        self,
    ) -> BrokerType:
        return self._broker

    @property
    def account_id(
        self,
    ) -> BrokerAccountId:
        return self._account_id

    # ========================================================
    # State
    # ========================================================

    @property
    def latest_snapshot(
        self,
    ) -> AccountFundsSnapshot | None:
        with self._lock:
            return self._latest_snapshot

    @property
    def last_failure(
        self,
    ) -> str | None:
        with self._lock:
            return self._last_failure

    @property
    def funds_available(
        self,
    ) -> bool:
        return (
            self.latest_snapshot
            is not None
        )

    @property
    def available_cash(
        self,
    ) -> Decimal | None:
        snapshot = self.latest_snapshot

        if snapshot is None:
            return None

        return snapshot.available_cash

    @property
    def available_margin(
        self,
    ) -> Decimal | None:
        snapshot = self.latest_snapshot

        if snapshot is None:
            return None

        return snapshot.available_margin

    @property
    def utilized_margin(
        self,
    ) -> Decimal | None:
        snapshot = self.latest_snapshot

        if snapshot is None:
            return None

        return snapshot.utilized_margin

    # ========================================================
    # Refresh
    # ========================================================

    def refresh(
        self,
        *,
        requested_at: datetime,
    ) -> AccountFundsSnapshot:
        """
        Fetch and validate latest broker funds state.

        Last known good snapshot is retained if a later refresh
        fails.

        T05/T06 will decide whether stale funds data may permit
        a new entry. This service only preserves observed state.
        """

        try:
            snapshot = (
                self._provider.fetch_funds(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    requested_at=(
                        requested_at
                    ),
                )
            )

        except Exception as exc:
            message = str(exc).strip()

            if not message:
                message = (
                    exc.__class__.__name__
                )

            with self._lock:
                self._last_failure = message

            raise AccountFundsFetchError(
                "account funds fetch failed: "
                f"{message}"
            ) from exc

        self._validate_snapshot(
            snapshot
        )

        with self._lock:
            self._latest_snapshot = snapshot
            self._last_failure = None

        return snapshot

    # ========================================================
    # Cash / margin helpers
    # ========================================================

    def has_available_cash(
        self,
        required_cash: Decimal,
    ) -> bool:
        """
        Conservative cash-only check.

        False is returned when no funds snapshot exists.

        Final broker-account eligibility remains T05's
        responsibility.
        """

        if required_cash < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        snapshot = self.latest_snapshot

        if snapshot is None:
            return False

        return snapshot.has_available_cash(
            required_cash
        )

    def cash_shortfall(
        self,
        required_cash: Decimal,
    ) -> Decimal | None:
        """
        Return missing cash amount.

        Returns:
            None
                when no funds snapshot exists.

            Decimal("0")
                when available cash is sufficient.

            positive Decimal
                when account cash is insufficient.
        """

        if required_cash < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        snapshot = self.latest_snapshot

        if snapshot is None:
            return None

        if (
            snapshot.available_cash
            >= required_cash
        ):
            return Decimal("0")

        return (
            required_cash
            - snapshot.available_cash
        )

    def requires_new_entry_block(
        self,
        *,
        required_cash: Decimal,
    ) -> bool:
        """
        Conservative funds-level BUY gate.

        True when:
            - funds state is unavailable
            - available cash is insufficient

        This is not the complete M09 eligibility policy.
        """

        if required_cash < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        snapshot = self.latest_snapshot

        if snapshot is None:
            return True

        return not snapshot.has_available_cash(
            required_cash
        )

    # ========================================================
    # Validation
    # ========================================================

    def _validate_snapshot(
        self,
        snapshot: AccountFundsSnapshot,
    ) -> None:
        if (
            snapshot.broker
            is not self._broker
        ):
            message = (
                "account funds provider "
                "returned mismatched broker"
            )

            with self._lock:
                self._last_failure = message

            raise AccountFundsFetchError(
                message
            )

        if (
            snapshot.account_id
            != self._account_id
        ):
            message = (
                "account funds provider "
                "returned mismatched account"
            )

            with self._lock:
                self._last_failure = message

            raise AccountFundsFetchError(
                message
            )