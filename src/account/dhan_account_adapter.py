"""
Phoenix M09 Dhan Account Adapter.

Maps DhanHQ SDK responses into Phoenix account-domain models.

Implements:
    - AccountProfileProvider
    - AccountFundsProvider
    - BrokerConnectivityProvider

The adapter intentionally does NOT:
    - place orders
    - modify M06 execution
    - persist account state
    - store credentials/tokens
    - own token generation or renewal

Session authentication/re-authentication is handled separately.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from src.account.account_types import (
    AccountFundsSnapshot,
    AccountProfile,
    BrokerAccountId,
    BrokerAccountStatus,
    BrokerType,
)
from src.account.connectivity_monitor import (
    BrokerConnectivitySnapshot,
)


class DhanAccountAdapterError(
    RuntimeError
):
    """
    Dhan account API response could not be safely interpreted.
    """


class DhanAccountAdapter:
    """
    Broker-specific account/profile/funds/connectivity adapter.

    Parameters
    ----------
    dhan_client:
        Existing authenticated DhanHQ REST client.

        Phoenix should normally obtain this from the existing
        DhanBroker rather than constructing another execution
        client.

    profile_fetcher:
        Callable returning the Dhan User Profile response.

        This deliberately keeps the access token out of this
        adapter. Production wiring may implement the callable
        using DhanLogin.user_profile(access_token).

    account_id:
        Phoenix account identity expected from all Dhan
        responses.
    """

    def __init__(
        self,
        *,
        dhan_client: Any,
        profile_fetcher: Callable[
            [],
            Any,
        ],
        account_id: BrokerAccountId,
    ) -> None:
        self._dhan_client = dhan_client
        self._profile_fetcher = (
            profile_fetcher
        )
        self._account_id = account_id

    @property
    def broker(
        self,
    ) -> BrokerType:
        return BrokerType.DHAN

    @property
    def account_id(
        self,
    ) -> BrokerAccountId:
        return self._account_id

    # ========================================================
    # Account profile
    # ========================================================

    def fetch_profile(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        requested_at: datetime,
    ) -> AccountProfile:
        self._validate_requested_identity(
            broker=broker,
            account_id=account_id,
        )

        try:
            response = (
                self._profile_fetcher()
            )
        except Exception as exc:
            raise DhanAccountAdapterError(
                "Dhan user profile request failed: "
                f"{exc}"
            ) from exc

        data = self._extract_data(
            response,
            operation="user profile",
        )

        response_account_id = self._required_text(
            data,
            "dhanClientId",
            operation="user profile",
        )

        self._validate_dhan_account_id(
            response_account_id
        )

        active_segments = self._optional_text(
            data,
            "activeSegment",
        )

        # Phoenix trades NIFTY options, therefore derivative
        # segment availability is the account-level capability
        # required for new entries.
        trading_enabled = (
            self._derivative_segment_active(
                active_segments
            )
        )

        return AccountProfile(
            broker=BrokerType.DHAN,
            account_id=self._account_id,
            account_status=(
                BrokerAccountStatus.ACTIVE
            ),
            fetched_at=requested_at,
            client_name=None,
            trading_enabled=trading_enabled,
            product_type=active_segments,
        )

    # ========================================================
    # Funds
    # ========================================================

    def fetch_funds(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        requested_at: datetime,
    ) -> AccountFundsSnapshot:
        self._validate_requested_identity(
            broker=broker,
            account_id=account_id,
        )

        try:
            response = (
                self._dhan_client
                .get_fund_limits()
            )
        except Exception as exc:
            raise DhanAccountAdapterError(
                "Dhan fund-limit request failed: "
                f"{exc}"
            ) from exc

        data = self._extract_data(
            response,
            operation="fund limits",
        )

        response_account_id = self._required_text(
            data,
            "dhanClientId",
            operation="fund limits",
        )

        self._validate_dhan_account_id(
            response_account_id
        )

        # NOTE:
        # Dhan API currently spells this field
        # "availabelBalance".
        available_cash = self._decimal(
            data,
            "availabelBalance",
            operation="fund limits",
        )

        utilized_margin = self._decimal(
            data,
            "utilizedAmount",
            operation="fund limits",
        )

        collateral = self._decimal(
            data,
            "collateralAmount",
            operation="fund limits",
        )

        opening_balance = self._decimal(
            data,
            "sodLimit",
            operation="fund limits",
        )

        # Do NOT fabricate a second spendable amount from
        # collateral or SOD balance. M09-T04 deliberately uses
        # Dhan's available trading balance as available_cash.
        available_margin = Decimal(
            "0"
        )

        return AccountFundsSnapshot(
            broker=BrokerType.DHAN,
            account_id=self._account_id,
            available_cash=available_cash,
            available_margin=available_margin,
            utilized_margin=utilized_margin,
            collateral=collateral,
            opening_balance=opening_balance,
            fetched_at=requested_at,
        )

    # ========================================================
    # Connectivity
    # ========================================================

    def check_connectivity(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        checked_at: datetime,
    ) -> BrokerConnectivitySnapshot:
        """
        Use the Dhan User Profile endpoint as a lightweight
        authenticated connectivity check.

        A successful profile response proves both:
            - the API endpoint is reachable
            - the supplied token is accepted at that moment

        Session lifecycle policy still belongs to T02/T14.
        """

        self._validate_requested_identity(
            broker=broker,
            account_id=account_id,
        )

        try:
            response = (
                self._profile_fetcher()
            )

            data = self._extract_data(
                response,
                operation="connectivity",
            )

            response_account_id = (
                self._required_text(
                    data,
                    "dhanClientId",
                    operation="connectivity",
                )
            )

            self._validate_dhan_account_id(
                response_account_id
            )

        except Exception as exc:
            return BrokerConnectivitySnapshot(
                broker=BrokerType.DHAN,
                account_id=self._account_id,
                connected=False,
                checked_at=checked_at,
                message=str(exc),
            )

        return BrokerConnectivitySnapshot(
            broker=BrokerType.DHAN,
            account_id=self._account_id,
            connected=True,
            checked_at=checked_at,
        )

    # ========================================================
    # Response helpers
    # ========================================================

    @staticmethod
    def _extract_data(
        response: Any,
        *,
        operation: str,
    ) -> dict:
        """
        Support both raw Dhan dictionaries and common SDK
        envelopes containing a 'data' dictionary.
        """

        if not isinstance(
            response,
            dict,
        ):
            raise DhanAccountAdapterError(
                f"Dhan {operation} response "
                "must be a dictionary"
            )

        # Explicit broker error envelope.
        if (
            response.get("errorCode")
            or response.get("errorMessage")
        ):
            message = (
                response.get(
                    "errorMessage"
                )
                or response.get(
                    "errorCode"
                )
            )

            raise DhanAccountAdapterError(
                f"Dhan {operation} failed: "
                f"{message}"
            )

        data = response.get(
            "data",
            response,
        )

        if not isinstance(
            data,
            dict,
        ):
            raise DhanAccountAdapterError(
                f"Dhan {operation} data "
                "must be a dictionary"
            )

        return data

    @staticmethod
    def _required_text(
        data: dict,
        key: str,
        *,
        operation: str,
    ) -> str:
        value = data.get(
            key
        )

        if value is None:
            raise DhanAccountAdapterError(
                f"Dhan {operation} response "
                f"missing {key}"
            )

        text = str(
            value
        ).strip()

        if not text:
            raise DhanAccountAdapterError(
                f"Dhan {operation} response "
                f"contains empty {key}"
            )

        return text

    @staticmethod
    def _optional_text(
        data: dict,
        key: str,
    ) -> str | None:
        value = data.get(
            key
        )

        if value is None:
            return None

        text = str(
            value
        ).strip()

        return (
            text
            if text
            else None
        )

    @staticmethod
    def _decimal(
        data: dict,
        key: str,
        *,
        operation: str,
    ) -> Decimal:
        value = data.get(
            key
        )

        if value is None:
            raise DhanAccountAdapterError(
                f"Dhan {operation} response "
                f"missing {key}"
            )

        try:
            result = Decimal(
                str(value)
            )
        except (
            InvalidOperation,
            ValueError,
            TypeError,
        ) as exc:
            raise DhanAccountAdapterError(
                f"Dhan {operation} response "
                f"contains invalid {key}"
            ) from exc

        if result < Decimal("0"):
            raise DhanAccountAdapterError(
                f"Dhan {operation} response "
                f"contains negative {key}"
            )

        return result

    def _validate_requested_identity(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
    ) -> None:
        if broker is not BrokerType.DHAN:
            raise DhanAccountAdapterError(
                "Dhan adapter requires "
                "BrokerType.DHAN"
            )

        if (
            account_id
            != self._account_id
        ):
            raise DhanAccountAdapterError(
                "requested account does not "
                "match Dhan adapter account"
            )

    def _validate_dhan_account_id(
        self,
        response_account_id: str,
    ) -> None:
        if (
            response_account_id
            != self._account_id.value
        ):
            raise DhanAccountAdapterError(
                "Dhan response account does not "
                "match configured account"
            )

    @staticmethod
    def _derivative_segment_active(
        active_segments: str | None,
    ) -> bool:
        if active_segments is None:
            return False

        values = {
            part.strip().lower()
            for part
            in active_segments.split(",")
            if part.strip()
        }

        return (
            "derivative" in values
            or "derivatives" in values
        )