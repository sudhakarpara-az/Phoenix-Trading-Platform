"""
Phoenix M09 Account State Registry.

Responsibilities:
    - retain latest account-domain state
    - keep state isolated by BrokerAccountId
    - validate broker/account identity consistency
    - provide immutable aggregate account snapshots
    - support clear/reset operations

This module does NOT:
    - call Dhan
    - authenticate
    - fetch profile/funds
    - perform connectivity checks
    - decide eligibility
    - persist state

Persistence arrives in M09-T08/T09.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from src.account.account_types import (
    AccountFundsSnapshot,
    AccountHealthSnapshot,
    AccountProfile,
    AccountTradingEligibility,
    BrokerAccountId,
    BrokerSessionSnapshot,
    BrokerType,
)
from src.account.connectivity_monitor import (
    BrokerConnectivitySnapshot,
)


@dataclass(
    frozen=True,
    slots=True,
)
class AccountStateSnapshot:
    broker: BrokerType

    account_id: BrokerAccountId

    updated_at: datetime

    session: BrokerSessionSnapshot | None = None

    profile: AccountProfile | None = None

    funds: AccountFundsSnapshot | None = None

    connectivity: BrokerConnectivitySnapshot | None = None

    health: AccountHealthSnapshot | None = None

    eligibility: AccountTradingEligibility | None = None

    @property
    def session_available(
        self,
    ) -> bool:
        return self.session is not None

    @property
    def profile_available(
        self,
    ) -> bool:
        return self.profile is not None

    @property
    def funds_available(
        self,
    ) -> bool:
        return self.funds is not None

    @property
    def connectivity_available(
        self,
    ) -> bool:
        return self.connectivity is not None

    @property
    def health_available(
        self,
    ) -> bool:
        return self.health is not None

    @property
    def eligibility_available(
        self,
    ) -> bool:
        return self.eligibility is not None


class AccountStateNotFoundError(
    KeyError
):
    pass


class AccountStateIdentityError(
    ValueError
):
    pass


class AccountStateRegistry:
    """
    Thread-safe in-memory account state registry.
    """

    def __init__(
        self,
    ) -> None:
        self._states: dict[
            BrokerAccountId,
            AccountStateSnapshot,
        ] = {}

        self._lock = RLock()

    # ========================================================
    # Account lifecycle
    # ========================================================

    def register_account(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        registered_at: datetime,
    ) -> AccountStateSnapshot:
        with self._lock:
            existing = self._states.get(
                account_id
            )

            if existing is not None:
                if existing.broker is not broker:
                    raise AccountStateIdentityError(
                        "account already registered "
                        "with different broker"
                    )

                return existing

            snapshot = AccountStateSnapshot(
                broker=broker,
                account_id=account_id,
                updated_at=registered_at,
            )

            self._states[
                account_id
            ] = snapshot

            return snapshot

    def contains(
        self,
        account_id: BrokerAccountId,
    ) -> bool:
        with self._lock:
            return (
                account_id
                in self._states
            )

    def get(
        self,
        account_id: BrokerAccountId,
    ) -> AccountStateSnapshot | None:
        with self._lock:
            return self._states.get(
                account_id
            )

    def require(
        self,
        account_id: BrokerAccountId,
    ) -> AccountStateSnapshot:
        snapshot = self.get(
            account_id
        )

        if snapshot is None:
            raise AccountStateNotFoundError(
                f"account state not found: "
                f"{account_id.value}"
            )

        return snapshot

    def accounts(
        self,
    ) -> tuple[
        AccountStateSnapshot,
        ...
    ]:
        with self._lock:
            return tuple(
                self._states.values()
            )

    # ========================================================
    # Updates
    # ========================================================

    def update_session(
        self,
        snapshot: BrokerSessionSnapshot,
    ) -> AccountStateSnapshot:
        return self._update(
            account_id=(
                snapshot.account_id
            ),
            broker=snapshot.broker,
            updated_at=(
                snapshot.updated_at
            ),
            session=snapshot,
        )

    def update_profile(
        self,
        snapshot: AccountProfile,
    ) -> AccountStateSnapshot:
        return self._update(
            account_id=(
                snapshot.account_id
            ),
            broker=snapshot.broker,
            updated_at=(
                snapshot.fetched_at
            ),
            profile=snapshot,
        )

    def update_funds(
        self,
        snapshot: AccountFundsSnapshot,
    ) -> AccountStateSnapshot:
        return self._update(
            account_id=(
                snapshot.account_id
            ),
            broker=snapshot.broker,
            updated_at=(
                snapshot.fetched_at
            ),
            funds=snapshot,
        )

    def update_connectivity(
        self,
        snapshot:
            BrokerConnectivitySnapshot,
    ) -> AccountStateSnapshot:
        return self._update(
            account_id=(
                snapshot.account_id
            ),
            broker=snapshot.broker,
            updated_at=(
                snapshot.checked_at
            ),
            connectivity=snapshot,
        )

    def update_health(
        self,
        snapshot:
            AccountHealthSnapshot,
    ) -> AccountStateSnapshot:
        return self._update(
            account_id=(
                snapshot.account_id
            ),
            broker=snapshot.broker,
            updated_at=(
                snapshot.checked_at
            ),
            health=snapshot,
        )

    def update_eligibility(
        self,
        snapshot:
            AccountTradingEligibility,
    ) -> AccountStateSnapshot:
        return self._update(
            account_id=(
                snapshot.account_id
            ),
            broker=snapshot.broker,
            updated_at=(
                snapshot.evaluated_at
            ),
            eligibility=snapshot,
        )

    # ========================================================
    # Reset / removal
    # ========================================================

    def remove(
        self,
        account_id: BrokerAccountId,
    ) -> bool:
        with self._lock:
            if (
                account_id
                not in self._states
            ):
                return False

            del self._states[
                account_id
            ]

            return True

    def clear(
        self,
    ) -> None:
        with self._lock:
            self._states.clear()

    # ========================================================
    # Internal update
    # ========================================================

    def _update(
        self,
        *,
        account_id: BrokerAccountId,
        broker: BrokerType,
        updated_at: datetime,
        session=...,
        profile=...,
        funds=...,
        connectivity=...,
        health=...,
        eligibility=...,
    ) -> AccountStateSnapshot:
        with self._lock:
            current = self._states.get(
                account_id
            )

            if current is None:
                raise AccountStateNotFoundError(
                    "account must be registered "
                    f"before update: "
                    f"{account_id.value}"
                )

            if current.broker is not broker:
                raise AccountStateIdentityError(
                    "account update broker does not "
                    "match registered broker"
                )

            next_snapshot = AccountStateSnapshot(
                broker=current.broker,
                account_id=(
                    current.account_id
                ),
                updated_at=updated_at,
                session=(
                    current.session
                    if session is ...
                    else session
                ),
                profile=(
                    current.profile
                    if profile is ...
                    else profile
                ),
                funds=(
                    current.funds
                    if funds is ...
                    else funds
                ),
                connectivity=(
                    current.connectivity
                    if connectivity is ...
                    else connectivity
                ),
                health=(
                    current.health
                    if health is ...
                    else health
                ),
                eligibility=(
                    current.eligibility
                    if eligibility is ...
                    else eligibility
                ),
            )

            self._states[
                account_id
            ] = next_snapshot

            return next_snapshot