"""
Phoenix M09 Broker Connectivity Monitor.

Responsibilities:
    - query broker connectivity through a provider boundary
    - validate broker/account identity
    - retain latest connectivity snapshot
    - track last successful connectivity check
    - track consecutive connectivity failures
    - expose conservative new-entry connectivity readiness

This module does NOT:
    - authenticate sessions
    - fetch account profile
    - fetch funds
    - place orders
    - persist connectivity
    - call Dhan directly

Dhan-specific connectivity mapping belongs to M09-T10.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol

from src.account.account_types import (
    BrokerAccountId,
    BrokerType,
)


@dataclass(
    frozen=True,
    slots=True,
)
class BrokerConnectivitySnapshot:
    """
    Point-in-time broker connectivity state.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    connected: bool

    checked_at: datetime

    message: str | None = None

    latency_ms: float | None = None

    def __post_init__(
        self,
    ) -> None:
        if (
            self.latency_ms is not None
            and self.latency_ms < 0
        ):
            raise ValueError(
                "connectivity latency cannot be negative"
            )

        if self.message is not None:
            message = self.message.strip()

            if not message:
                raise ValueError(
                    "connectivity message cannot be empty"
                )

            if message != self.message:
                object.__setattr__(
                    self,
                    "message",
                    message,
                )


class BrokerConnectivityProvider(
    Protocol,
):
    """
    Broker-independent connectivity source.

    Concrete Dhan implementation will be added later.
    """

    def check_connectivity(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        checked_at: datetime,
    ) -> BrokerConnectivitySnapshot:
        ...


class BrokerConnectivityCheckError(
    RuntimeError
):
    """
    Connectivity check or validation failed.
    """


class BrokerConnectivityMonitor:
    """
    Owns current connectivity state for one broker account.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        provider: BrokerConnectivityProvider,
    ) -> None:
        self._broker = broker
        self._account_id = account_id
        self._provider = provider

        self._latest_snapshot: (
            BrokerConnectivitySnapshot
            | None
        ) = None

        self._last_success_at: (
            datetime
            | None
        ) = None

        self._last_failure: (
            str
            | None
        ) = None

        self._consecutive_failures = 0

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
    ) -> BrokerConnectivitySnapshot | None:
        with self._lock:
            return self._latest_snapshot

    @property
    def last_success_at(
        self,
    ) -> datetime | None:
        with self._lock:
            return self._last_success_at

    @property
    def last_failure(
        self,
    ) -> str | None:
        with self._lock:
            return self._last_failure

    @property
    def consecutive_failures(
        self,
    ) -> int:
        with self._lock:
            return self._consecutive_failures

    @property
    def connectivity_known(
        self,
    ) -> bool:
        return (
            self.latest_snapshot
            is not None
        )

    @property
    def connected(
        self,
    ) -> bool:
        snapshot = self.latest_snapshot

        return (
            snapshot is not None
            and snapshot.connected
        )

    @property
    def usable_for_new_entries(
        self,
    ) -> bool:
        """
        Connectivity-level BUY gate only.
        """

        return self.connected

    # ========================================================
    # Check
    # ========================================================

    def check(
        self,
        *,
        checked_at: datetime,
    ) -> BrokerConnectivitySnapshot:
        """
        Perform one broker connectivity check.

        Provider exceptions are converted into an explicit
        disconnected snapshot and raised as
        BrokerConnectivityCheckError.
        """

        try:
            snapshot = (
                self._provider
                .check_connectivity(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    checked_at=checked_at,
                )
            )

        except Exception as exc:
            message = str(exc).strip()

            if not message:
                message = (
                    exc.__class__.__name__
                )

            failed_snapshot = (
                BrokerConnectivitySnapshot(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    connected=False,
                    checked_at=checked_at,
                    message=message,
                )
            )

            with self._lock:
                self._latest_snapshot = (
                    failed_snapshot
                )

                self._last_failure = message

                self._consecutive_failures += 1

            raise BrokerConnectivityCheckError(
                "broker connectivity check failed: "
                f"{message}"
            ) from exc

        self._validate_snapshot(
            snapshot
        )

        with self._lock:
            self._latest_snapshot = snapshot

            if snapshot.connected:
                self._last_success_at = (
                    snapshot.checked_at
                )

                self._last_failure = None
                self._consecutive_failures = 0

            else:
                message = (
                    snapshot.message
                    or "broker disconnected"
                )

                self._last_failure = message

                self._consecutive_failures += 1

        return snapshot

    # ========================================================
    # Safety
    # ========================================================

    def requires_new_entry_block(
        self,
    ) -> bool:
        """
        Conservative connectivity gate.

        Unknown or disconnected state blocks new BUYs.
        """

        return not self.connected

    # ========================================================
    # Validation
    # ========================================================

    def _validate_snapshot(
        self,
        snapshot: BrokerConnectivitySnapshot,
    ) -> None:
        if (
            snapshot.broker
            is not self._broker
        ):
            message = (
                "connectivity provider "
                "returned mismatched broker"
            )

            with self._lock:
                self._last_failure = message
                self._consecutive_failures += 1

            raise BrokerConnectivityCheckError(
                message
            )

        if (
            snapshot.account_id
            != self._account_id
        ):
            message = (
                "connectivity provider "
                "returned mismatched account"
            )

            with self._lock:
                self._last_failure = message
                self._consecutive_failures += 1

            raise BrokerConnectivityCheckError(
                message
            )