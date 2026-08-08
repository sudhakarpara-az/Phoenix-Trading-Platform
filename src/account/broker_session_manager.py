"""
Phoenix M09 Broker Session Manager.

Responsibilities:
    - manage broker authentication/session lifecycle
    - expose current immutable BrokerSessionSnapshot
    - prevent invalid session transitions
    - detect session expiry
    - fail closed when authentication fails
    - close broker sessions safely

This module does NOT:
    - call Dhan directly
    - store credentials
    - persist sessions
    - place orders
    - evaluate strategy/risk rules

Dhan-specific authentication belongs to a later M09 adapter.
"""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Protocol

from src.account.account_types import (
    BrokerAccountId,
    BrokerSessionSnapshot,
    BrokerSessionStatus,
    BrokerType,
)


class BrokerSessionProvider(
    Protocol,
):
    """
    Authentication boundary used by BrokerSessionManager.

    Concrete Dhan implementation will be introduced later.
    """

    def authenticate(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        requested_at: datetime,
    ) -> BrokerSessionSnapshot:
        ...

    def close(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        requested_at: datetime,
    ) -> None:
        ...


class BrokerSessionTransitionError(
    RuntimeError
):
    """
    Invalid broker-session lifecycle transition.
    """


class BrokerSessionAuthenticationError(
    RuntimeError
):
    """
    Broker authentication failed.
    """


class BrokerSessionManager:
    """
    Manages one Phoenix broker account session.

    The manager owns session state but delegates actual
    authentication to BrokerSessionProvider.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        provider: BrokerSessionProvider,
        created_at: datetime,
    ) -> None:
        self._broker = broker

        self._account_id = account_id

        self._provider = provider

        self._lock = RLock()

        self._snapshot = BrokerSessionSnapshot(
            broker=broker,
            account_id=account_id,
            status=(
                BrokerSessionStatus
                .NOT_INITIALIZED
            ),
            updated_at=created_at,
        )

    # ========================================================
    # Public state
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

    @property
    def snapshot(
        self,
    ) -> BrokerSessionSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def status(
        self,
    ) -> BrokerSessionStatus:
        return self.snapshot.status

    @property
    def authenticated(
        self,
    ) -> bool:
        return self.snapshot.authenticated

    @property
    def usable_for_new_entries(
        self,
    ) -> bool:
        return (
            self.snapshot
            .usable_for_new_entries
        )

    # ========================================================
    # Authentication
    # ========================================================

    def authenticate(
        self,
        *,
        requested_at: datetime,
    ) -> BrokerSessionSnapshot:
        """
        Authenticate broker session.

        Allowed from:
            NOT_INITIALIZED
            EXPIRED
            FAILED

        CLOSED sessions cannot be reused.
        """

        with self._lock:
            if self._snapshot.status not in {
                BrokerSessionStatus
                .NOT_INITIALIZED,

                BrokerSessionStatus
                .EXPIRED,

                BrokerSessionStatus
                .FAILED,
            }:
                raise BrokerSessionTransitionError(
                    "broker session cannot authenticate "
                    f"from {self._snapshot.status.value}"
                )

            self._snapshot = (
                BrokerSessionSnapshot(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    status=(
                        BrokerSessionStatus
                        .AUTHENTICATING
                    ),
                    updated_at=requested_at,
                )
            )

        try:
            snapshot = (
                self._provider.authenticate(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    requested_at=requested_at,
                )
            )

        except Exception as exc:
            failed = (
                BrokerSessionSnapshot(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    status=(
                        BrokerSessionStatus
                        .FAILED
                    ),
                    updated_at=requested_at,
                    failure_message=str(exc),
                )
            )

            with self._lock:
                self._snapshot = failed

            raise (
                BrokerSessionAuthenticationError(
                    "broker session "
                    f"authentication failed: {exc}"
                )
            ) from exc

        self._validate_provider_snapshot(
            snapshot
        )

        if (
            snapshot.status
            is not BrokerSessionStatus
            .AUTHENTICATED
        ):
            failed = (
                BrokerSessionSnapshot(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    status=(
                        BrokerSessionStatus
                        .FAILED
                    ),
                    updated_at=(
                        snapshot.updated_at
                    ),
                    failure_message=(
                        "broker provider did not "
                        "return AUTHENTICATED session"
                    ),
                )
            )

            with self._lock:
                self._snapshot = failed

            raise (
                BrokerSessionAuthenticationError(
                    "broker provider did not "
                    "return AUTHENTICATED session"
                )
            )

        with self._lock:
            self._snapshot = snapshot

        return snapshot

    # ========================================================
    # Expiry
    # ========================================================

    def refresh_expiry_state(
        self,
        *,
        checked_at: datetime,
    ) -> BrokerSessionSnapshot:
        """
        Mark an authenticated session EXPIRED once its expiry
        timestamp is reached.

        Sessions without an expires_at value remain unchanged.
        """

        with self._lock:
            snapshot = self._snapshot

            if (
                snapshot.status
                is not BrokerSessionStatus
                .AUTHENTICATED
            ):
                return snapshot

            if snapshot.expires_at is None:
                return snapshot

            if checked_at < snapshot.expires_at:
                return snapshot

            expired = BrokerSessionSnapshot(
                broker=snapshot.broker,
                account_id=(
                    snapshot.account_id
                ),
                status=(
                    BrokerSessionStatus
                    .EXPIRED
                ),
                authenticated_at=(
                    snapshot.authenticated_at
                ),
                expires_at=(
                    snapshot.expires_at
                ),
                updated_at=checked_at,
            )

            self._snapshot = expired

            return expired

    # ========================================================
    # Explicit failure
    # ========================================================

    def mark_failed(
        self,
        *,
        message: str,
        failed_at: datetime,
    ) -> BrokerSessionSnapshot:
        """
        Fail the current session explicitly.

        CLOSED sessions remain terminal.
        """

        with self._lock:
            if (
                self._snapshot.status
                is BrokerSessionStatus.CLOSED
            ):
                raise BrokerSessionTransitionError(
                    "CLOSED broker session "
                    "cannot transition to FAILED"
                )

            snapshot = BrokerSessionSnapshot(
                broker=self._broker,
                account_id=(
                    self._account_id
                ),
                status=(
                    BrokerSessionStatus.FAILED
                ),
                updated_at=failed_at,
                failure_message=message,
            )

            self._snapshot = snapshot

            return snapshot

    # ========================================================
    # Close
    # ========================================================

    def close(
        self,
        *,
        requested_at: datetime,
    ) -> BrokerSessionSnapshot:
        """
        Close broker session.

        close() is idempotent once already CLOSED.
        """

        with self._lock:
            if (
                self._snapshot.status
                is BrokerSessionStatus.CLOSED
            ):
                return self._snapshot

        try:
            self._provider.close(
                broker=self._broker,
                account_id=(
                    self._account_id
                ),
                requested_at=requested_at,
            )

        except Exception as exc:
            return self.mark_failed(
                message=(
                    "broker session close failed: "
                    f"{exc}"
                ),
                failed_at=requested_at,
            )

        snapshot = BrokerSessionSnapshot(
            broker=self._broker,
            account_id=(
                self._account_id
            ),
            status=(
                BrokerSessionStatus.CLOSED
            ),
            updated_at=requested_at,
        )

        with self._lock:
            self._snapshot = snapshot

        return snapshot

    # ========================================================
    # Helpers
    # ========================================================

    def _validate_provider_snapshot(
        self,
        snapshot: BrokerSessionSnapshot,
    ) -> None:
        if (
            snapshot.broker
            is not self._broker
        ):
            raise (
                BrokerSessionAuthenticationError(
                    "broker session provider "
                    "returned mismatched broker"
                )
            )

        if (
            snapshot.account_id
            != self._account_id
        ):
            raise (
                BrokerSessionAuthenticationError(
                    "broker session provider "
                    "returned mismatched account"
                )
            )