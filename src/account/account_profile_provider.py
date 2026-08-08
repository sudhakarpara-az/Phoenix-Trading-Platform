"""
Phoenix M09 Account Profile Provider boundary and service.

Responsibilities:
    - fetch broker account profile through a provider boundary
    - validate broker/account identity
    - preserve immutable AccountProfile domain models
    - retain latest successfully fetched profile
    - fail closed when profile retrieval fails
    - expose whether the account profile permits trading

This module does NOT:
    - authenticate broker sessions
    - query funds/margin
    - place orders
    - persist account records
    - call Dhan directly

Dhan-specific mapping belongs to M09-T10.
"""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Protocol

from src.account.account_types import (
    AccountProfile,
    BrokerAccountId,
    BrokerAccountStatus,
    BrokerType,
)


class AccountProfileProvider(
    Protocol,
):
    """
    Broker-independent account-profile source.

    Concrete Dhan implementation will be introduced later.
    """

    def fetch_profile(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        requested_at: datetime,
    ) -> AccountProfile:
        ...


class AccountProfileFetchError(
    RuntimeError
):
    """
    Account profile retrieval or validation failed.
    """


class AccountProfileService:
    """
    Owns the latest validated profile for one broker account.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        provider: AccountProfileProvider,
    ) -> None:
        self._broker = broker

        self._account_id = account_id

        self._provider = provider

        self._latest_profile: (
            AccountProfile
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
    def latest_profile(
        self,
    ) -> AccountProfile | None:
        with self._lock:
            return self._latest_profile

    @property
    def last_failure(
        self,
    ) -> str | None:
        with self._lock:
            return self._last_failure

    @property
    def profile_available(
        self,
    ) -> bool:
        return (
            self.latest_profile
            is not None
        )

    @property
    def account_active(
        self,
    ) -> bool:
        profile = self.latest_profile

        return (
            profile is not None
            and profile.active
        )

    @property
    def trading_enabled(
        self,
    ) -> bool:
        profile = self.latest_profile

        return (
            profile is not None
            and profile.trading_enabled
        )

    @property
    def eligible_account_state(
        self,
    ) -> bool:
        profile = self.latest_profile

        return (
            profile is not None
            and profile.eligible_account_state
        )

    # ========================================================
    # Fetch
    # ========================================================

    def refresh(
        self,
        *,
        requested_at: datetime,
    ) -> AccountProfile:
        """
        Fetch and validate the latest broker account profile.

        Last known good profile is retained if a later refresh
        fails. The failure remains separately observable through
        last_failure.

        Eligibility policy in T05 will decide whether stale
        profile data may be trusted; this service does not make
        that policy decision.
        """

        try:
            profile = (
                self._provider.fetch_profile(
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

            raise AccountProfileFetchError(
                "account profile fetch failed: "
                f"{message}"
            ) from exc

        self._validate_profile(
            profile
        )

        with self._lock:
            self._latest_profile = profile
            self._last_failure = None

        return profile

    # ========================================================
    # Safety helpers
    # ========================================================

    def requires_new_entry_block(
        self,
    ) -> bool:
        """
        Conservative account-profile gate.

        True means account profile state alone is insufficient
        to permit a new BUY.

        T05 will produce the detailed eligibility reason.
        """

        profile = self.latest_profile

        if profile is None:
            return True

        return not (
            profile.eligible_account_state
        )

    def account_status(
        self,
    ) -> BrokerAccountStatus:
        profile = self.latest_profile

        if profile is None:
            return (
                BrokerAccountStatus.UNKNOWN
            )

        return profile.account_status

    # ========================================================
    # Validation
    # ========================================================

    def _validate_profile(
        self,
        profile: AccountProfile,
    ) -> None:
        if (
            profile.broker
            is not self._broker
        ):
            message = (
                "account profile provider "
                "returned mismatched broker"
            )

            with self._lock:
                self._last_failure = message

            raise AccountProfileFetchError(
                message
            )

        if (
            profile.account_id
            != self._account_id
        ):
            message = (
                "account profile provider "
                "returned mismatched account"
            )

            with self._lock:
                self._last_failure = message

            raise AccountProfileFetchError(
                message
            )