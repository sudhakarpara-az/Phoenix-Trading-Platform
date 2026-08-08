"""
Phoenix M09 Session Expiry / Re-authentication Service.

Responsibilities:
    - refresh session expiry state
    - detect when re-authentication is required
    - prevent concurrent re-authentication attempts
    - invoke BrokerSessionManager authentication safely
    - expose latest re-authentication outcome
    - fail closed while session state is uncertain

This module does NOT:
    - store credentials
    - generate Dhan tokens directly
    - place orders
    - evaluate account funds/profile
    - persist session state

BrokerSessionManager remains the owner of session lifecycle
state. This service coordinates safe re-authentication.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from src.account.account_types import (
    BrokerAccountId,
    BrokerSessionSnapshot,
    BrokerSessionStatus,
    BrokerType,
)
from src.account.broker_session_manager import (
    BrokerSessionAuthenticationError,
    BrokerSessionManager,
)


@dataclass(
    frozen=True,
    slots=True,
)
class SessionReauthResult:
    """
    Result of one session validation / re-auth cycle.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    snapshot: BrokerSessionSnapshot

    checked_at: datetime

    reauth_attempted: bool

    reauth_succeeded: bool

    message: str | None = None

    @property
    def authenticated(
        self,
    ) -> bool:
        return (
            self.snapshot.status
            is BrokerSessionStatus.AUTHENTICATED
        )

    @property
    def usable_for_new_entries(
        self,
    ) -> bool:
        return self.authenticated


class SessionReauthInProgressError(
    RuntimeError
):
    """
    Another re-authentication attempt is already active.
    """


class SessionReauthService:
    """
    Coordinates safe BrokerSessionManager re-authentication.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        session_manager: BrokerSessionManager,
    ) -> None:
        self._broker = broker
        self._account_id = account_id
        self._session_manager = (
            session_manager
        )

        self._reauth_lock = Lock()

        self._last_result: (
            SessionReauthResult
            | None
        ) = None

        self._validate_identity()

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
    def last_result(
        self,
    ) -> SessionReauthResult | None:
        return self._last_result

    # ========================================================
    # Session validation
    # ========================================================

    def ensure_authenticated(
        self,
        *,
        checked_at: datetime,
    ) -> SessionReauthResult:
        """
        Ensure the broker session is currently authenticated.

        Behavior:
            AUTHENTICATED + not expired
                -> return existing session

            EXPIRED / FAILED / NOT_INITIALIZED
                -> attempt authentication

            AUTHENTICATING
                -> fail closed; do not start another attempt

            CLOSED
                -> fail closed; closed manager is terminal
        """

        snapshot = (
            self._session_manager
            .refresh_expiry_state(
                checked_at=checked_at
            )
        )

        if (
            snapshot.status
            is BrokerSessionStatus.AUTHENTICATED
        ):
            result = SessionReauthResult(
                broker=self._broker,
                account_id=self._account_id,
                snapshot=snapshot,
                checked_at=checked_at,
                reauth_attempted=False,
                reauth_succeeded=False,
            )

            self._last_result = result

            return result

        if (
            snapshot.status
            is BrokerSessionStatus.AUTHENTICATING
        ):
            result = SessionReauthResult(
                broker=self._broker,
                account_id=self._account_id,
                snapshot=snapshot,
                checked_at=checked_at,
                reauth_attempted=False,
                reauth_succeeded=False,
                message=(
                    "broker session authentication "
                    "already in progress"
                ),
            )

            self._last_result = result

            raise SessionReauthInProgressError(
                result.message
            )

        if (
            snapshot.status
            is BrokerSessionStatus.CLOSED
        ):
            result = SessionReauthResult(
                broker=self._broker,
                account_id=self._account_id,
                snapshot=snapshot,
                checked_at=checked_at,
                reauth_attempted=False,
                reauth_succeeded=False,
                message=(
                    "closed broker session "
                    "cannot be re-authenticated"
                ),
            )

            self._last_result = result

            return result

        return self._reauthenticate(
            requested_at=checked_at
        )

    # ========================================================
    # Explicit re-auth
    # ========================================================

    def reauthenticate(
        self,
        *,
        requested_at: datetime,
    ) -> SessionReauthResult:
        """
        Explicit re-authentication request.

        Intended for:
            EXPIRED
            FAILED
            NOT_INITIALIZED

        Concurrent attempts are rejected.
        """

        snapshot = (
            self._session_manager.snapshot
        )

        if (
            snapshot.status
            is BrokerSessionStatus.AUTHENTICATED
        ):
            result = SessionReauthResult(
                broker=self._broker,
                account_id=self._account_id,
                snapshot=snapshot,
                checked_at=requested_at,
                reauth_attempted=False,
                reauth_succeeded=False,
                message=(
                    "session already authenticated"
                ),
            )

            self._last_result = result

            return result

        if (
            snapshot.status
            is BrokerSessionStatus.CLOSED
        ):
            result = SessionReauthResult(
                broker=self._broker,
                account_id=self._account_id,
                snapshot=snapshot,
                checked_at=requested_at,
                reauth_attempted=False,
                reauth_succeeded=False,
                message=(
                    "closed broker session "
                    "cannot be re-authenticated"
                ),
            )

            self._last_result = result

            return result

        return self._reauthenticate(
            requested_at=requested_at
        )

    # ========================================================
    # Internal
    # ========================================================

    def _reauthenticate(
        self,
        *,
        requested_at: datetime,
    ) -> SessionReauthResult:
        acquired = (
            self._reauth_lock
            .acquire(
                blocking=False
            )
        )

        if not acquired:
            raise SessionReauthInProgressError(
                "broker session re-authentication "
                "already in progress"
            )

        try:
            try:
                snapshot = (
                    self._session_manager
                    .authenticate(
                        requested_at=(
                            requested_at
                        )
                    )
                )

            except (
                BrokerSessionAuthenticationError
            ) as exc:
                snapshot = (
                    self._session_manager
                    .snapshot
                )

                result = (
                    SessionReauthResult(
                        broker=self._broker,
                        account_id=(
                            self._account_id
                        ),
                        snapshot=snapshot,
                        checked_at=(
                            requested_at
                        ),
                        reauth_attempted=True,
                        reauth_succeeded=False,
                        message=str(exc),
                    )
                )

                self._last_result = result

                return result

            result = SessionReauthResult(
                broker=self._broker,
                account_id=self._account_id,
                snapshot=snapshot,
                checked_at=requested_at,
                reauth_attempted=True,
                reauth_succeeded=True,
            )

            self._last_result = result

            return result

        finally:
            self._reauth_lock.release()

    def _validate_identity(
        self,
    ) -> None:
        if (
            self._session_manager.broker
            is not self._broker
        ):
            raise ValueError(
                "session reauth service "
                "broker mismatch"
            )

        if (
            self._session_manager.account_id
            != self._account_id
        ):
            raise ValueError(
                "session reauth service "
                "account mismatch"
            )