"""
Phoenix M09 Account Runtime Service.

Application-level integration boundary between:

    M08 Runtime
        and
    M09 Broker / Account Management

Responsibilities:
    - register the configured broker account
    - refresh broker connectivity
    - refresh account profile
    - refresh funds
    - derive account health
    - derive new-entry eligibility
    - update AccountStateRegistry
    - provide one aggregate account-runtime refresh result

This service does NOT:
    - call Dhan directly
    - place orders
    - persist account state
    - evaluate M07 risk
    - own M08 runtime transitions

Concrete Dhan access remains behind M09 providers/adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.account.account_eligibility_policy import (
    AccountTradingEligibilityPolicy,
)
from src.account.account_profile_provider import (
    AccountProfileFetchError,
    AccountProfileService,
)
from src.account.account_state_registry import (
    AccountStateRegistry,
    AccountStateSnapshot,
)
from src.account.account_types import (
    AccountEligibilityReason,
    AccountEligibilityStatus,
    AccountHealthSnapshot,
    AccountHealthStatus,
    AccountTradingEligibility,
    BrokerAccountId,
    BrokerType,
)
from src.account.broker_session_manager import (
    BrokerSessionManager,
)
from src.account.connectivity_monitor import (
    BrokerConnectivityCheckError,
    BrokerConnectivityMonitor,
)
from src.account.funds_provider import (
    AccountFundsFetchError,
    AccountFundsService,
)


@dataclass(
    frozen=True,
    slots=True,
)
class AccountRuntimeRefreshResult:
    account_state: AccountStateSnapshot

    health: AccountHealthSnapshot

    eligibility: AccountTradingEligibility

    refreshed_at: datetime

    @property
    def new_entries_allowed(
        self,
    ) -> bool:
        return self.eligibility.allowed


class AccountRuntimeService:
    """
    Coordinates M09 account components for one broker account.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        session_manager: BrokerSessionManager,
        profile_service: AccountProfileService,
        funds_service: AccountFundsService,
        connectivity_monitor: BrokerConnectivityMonitor,
        eligibility_policy: AccountTradingEligibilityPolicy,
        state_registry: AccountStateRegistry,
    ) -> None:
        self._broker = broker
        self._account_id = account_id

        self._session_manager = (
            session_manager
        )

        self._profile_service = (
            profile_service
        )

        self._funds_service = (
            funds_service
        )

        self._connectivity_monitor = (
            connectivity_monitor
        )

        self._eligibility_policy = (
            eligibility_policy
        )

        self._state_registry = (
            state_registry
        )

        self._validate_components()

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
    # Registration
    # ========================================================

    def ensure_registered(
        self,
        *,
        registered_at: datetime,
    ) -> AccountStateSnapshot:
        return (
            self._state_registry
            .register_account(
                broker=self._broker,
                account_id=self._account_id,
                registered_at=registered_at,
            )
        )

    # ========================================================
    # Refresh
    # ========================================================

    def refresh(
        self,
        *,
        required_cash: Decimal,
        refreshed_at: datetime,
    ) -> AccountRuntimeRefreshResult:
        """
        Refresh all required M09 account state.

        Fetch failures are converted into conservative health /
        eligibility state rather than allowing a new BUY.

        This method intentionally does not fail the M08 runtime
        by itself. M08 integration policy decides whether an
        unhealthy account should fail startup or merely block
        entries.
        """

        if required_cash < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        self.ensure_registered(
            registered_at=refreshed_at
        )

        # ----------------------------------------------------
        # Session
        # ----------------------------------------------------

        session = (
            self._session_manager.snapshot
        )

        self._state_registry.update_session(
            session
        )

        # ----------------------------------------------------
        # Connectivity
        # ----------------------------------------------------

        connectivity = None

        try:
            connectivity = (
                self._connectivity_monitor
                .check(
                    checked_at=refreshed_at
                )
            )

        except BrokerConnectivityCheckError:
            connectivity = (
                self._connectivity_monitor
                .latest_snapshot
            )

        if connectivity is not None:
            (
                self._state_registry
                .update_connectivity(
                    connectivity
                )
            )

        # ----------------------------------------------------
        # Profile
        # ----------------------------------------------------

        profile = None

        try:
            profile = (
                self._profile_service
                .refresh(
                    requested_at=(
                        refreshed_at
                    )
                )
            )

        except AccountProfileFetchError:
            profile = (
                self._profile_service
                .latest_profile
            )

        if profile is not None:
            self._state_registry.update_profile(
                profile
            )

        # ----------------------------------------------------
        # Funds
        # ----------------------------------------------------

        funds_snapshot = None

        try:
            funds_snapshot = (
                self._funds_service
                .refresh(
                    requested_at=(
                        refreshed_at
                    )
                )
            )

        except AccountFundsFetchError:
            funds_snapshot = (
                self._funds_service
                .latest_snapshot
            )

        if funds_snapshot is not None:
            self._state_registry.update_funds(
                funds_snapshot
            )

        # ----------------------------------------------------
        # Health
        # ----------------------------------------------------

        health = self._build_health(
            refreshed_at=refreshed_at,
        )

        self._state_registry.update_health(
            health
        )

        # ----------------------------------------------------
        # Eligibility
        # ----------------------------------------------------

        eligibility = (
            self._build_eligibility(
                required_cash=required_cash,
                evaluated_at=refreshed_at,
            )
        )

        self._state_registry.update_eligibility(
            eligibility
        )

        state = self._state_registry.require(
            self._account_id
        )

        return AccountRuntimeRefreshResult(
            account_state=state,
            health=health,
            eligibility=eligibility,
            refreshed_at=refreshed_at,
        )

    # ========================================================
    # Health
    # ========================================================

    def _build_health(
        self,
        *,
        refreshed_at: datetime,
    ) -> AccountHealthSnapshot:
        connectivity = (
            self._connectivity_monitor
            .latest_snapshot
        )

        broker_connected = (
            connectivity is not None
            and connectivity.connected
        )

        session_authenticated = (
            self._session_manager
            .authenticated
        )

        profile_available = (
            self._profile_service
            .profile_available
            and self._profile_service
            .last_failure
            is None
        )

        funds_available = (
            self._funds_service
            .funds_available
            and self._funds_service
            .last_failure
            is None
        )

        if (
            broker_connected
            and session_authenticated
            and profile_available
            and funds_available
        ):
            status = (
                AccountHealthStatus
                .HEALTHY
            )

            message = None

        elif (
            not broker_connected
            or not session_authenticated
        ):
            status = (
                AccountHealthStatus
                .UNHEALTHY
            )

            message = (
                "critical account dependency "
                "unavailable"
            )

        else:
            status = (
                AccountHealthStatus
                .DEGRADED
            )

            message = (
                "account state partially unavailable"
            )

        return AccountHealthSnapshot(
            broker=self._broker,
            account_id=self._account_id,
            status=status,
            checked_at=refreshed_at,
            broker_connected=(
                broker_connected
            ),
            session_authenticated=(
                session_authenticated
            ),
            profile_available=(
                profile_available
            ),
            funds_available=(
                funds_available
            ),
            message=message,
        )

    # ========================================================
    # Eligibility
    # ========================================================

    def _build_eligibility(
        self,
        *,
        required_cash: Decimal,
        evaluated_at: datetime,
    ) -> AccountTradingEligibility:
        connectivity = (
            self._connectivity_monitor
            .latest_snapshot
        )

        if connectivity is None:
            return (
                AccountTradingEligibility
                .block(
                    broker=self._broker,
                    account_id=(
                        self._account_id
                    ),
                    reason=(
                        AccountEligibilityReason
                        .BROKER_UNAVAILABLE
                    ),
                    evaluated_at=(
                        evaluated_at
                    ),
                    message=(
                        "broker connectivity "
                        "state unavailable"
                    ),
                    required_cash=(
                        required_cash
                    ),
                )
            )

        return (
            self._eligibility_policy
            .evaluate(
                session=(
                    self._session_manager
                    .snapshot
                ),
                profile=(
                    self._profile_service
                    .latest_profile
                ),
                funds=(
                    self._funds_service
                ),
                connectivity=(
                    connectivity
                ),
                required_cash=(
                    required_cash
                ),
                evaluated_at=(
                    evaluated_at
                ),
            )
        )

    # ========================================================
    # Component identity safety
    # ========================================================

    def _validate_components(
        self,
    ) -> None:
        components = (
            self._session_manager,
            self._profile_service,
            self._funds_service,
            self._connectivity_monitor,
        )

        for component in components:
            if (
                component.broker
                is not self._broker
            ):
                raise ValueError(
                    "account runtime component "
                    "broker mismatch"
                )

            if (
                component.account_id
                != self._account_id
            ):
                raise ValueError(
                    "account runtime component "
                    "account mismatch"
                )