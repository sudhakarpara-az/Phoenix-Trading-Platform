"""
Phoenix M09-T11 M08 -> M09 Runtime Integration tests.
"""

from datetime import (
    date,
    datetime,
)
from decimal import Decimal

from src.account.account_eligibility_policy import (
    AccountTradingEligibilityPolicy,
)
from src.account.account_profile_provider import (
    AccountProfileService,
)
from src.account.account_runtime_service import (
    AccountRuntimeService,
)
from src.account.account_state_registry import (
    AccountStateRegistry,
)
from src.account.account_types import (
    AccountFundsSnapshot,
    AccountHealthStatus,
    AccountProfile,
    BrokerAccountId,
    BrokerAccountStatus,
    BrokerSessionSnapshot,
    BrokerSessionStatus,
    BrokerType,
)
from src.account.broker_session_manager import (
    BrokerSessionManager,
)
from src.account.connectivity_monitor import (
    BrokerConnectivityMonitor,
    BrokerConnectivitySnapshot,
)
from src.account.funds_provider import (
    AccountFundsService,
)
from src.runtime.event_bus import (
    RuntimeEventBus,
)
from src.runtime.runtime_orchestrator import (
    TradingRuntimeOrchestrator,
)
from src.runtime.runtime_types import (
    RuntimeId,
    RuntimeMode,
    RuntimeState,
)


TODAY = date(
    2026,
    8,
    8,
)

NOW = datetime(
    2026,
    8,
    8,
    12,
    0,
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)

REQUIRED_CASH = Decimal(
    "6500"
)


class FakeSessionProvider:
    def authenticate(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        return BrokerSessionSnapshot(
            broker=broker,
            account_id=account_id,
            status=(
                BrokerSessionStatus
                .AUTHENTICATED
            ),
            authenticated_at=(
                requested_at
            ),
            updated_at=(
                requested_at
            ),
        )

    def close(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        del broker
        del account_id
        del requested_at


class FakeProfileProvider:
    def __init__(
        self,
    ):
        self.error = None

    def fetch_profile(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        if self.error is not None:
            raise self.error

        return AccountProfile(
            broker=broker,
            account_id=account_id,
            account_status=(
                BrokerAccountStatus.ACTIVE
            ),
            fetched_at=(
                requested_at
            ),
            trading_enabled=True,
        )


class FakeFundsProvider:
    def __init__(
        self,
    ):
        self.error = None
        self.cash = Decimal(
            "100000"
        )

    def fetch_funds(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        if self.error is not None:
            raise self.error

        return AccountFundsSnapshot(
            broker=broker,
            account_id=account_id,
            available_cash=self.cash,
            available_margin=Decimal(
                "0"
            ),
            utilized_margin=Decimal(
                "0"
            ),
            fetched_at=(
                requested_at
            ),
        )


class FakeConnectivityProvider:
    def __init__(
        self,
    ):
        self.connected = True
        self.error = None

    def check_connectivity(
        self,
        *,
        broker,
        account_id,
        checked_at,
    ):
        if self.error is not None:
            raise self.error

        return BrokerConnectivitySnapshot(
            broker=broker,
            account_id=account_id,
            connected=self.connected,
            checked_at=checked_at,
            message=(
                None
                if self.connected
                else "disconnected"
            ),
        )


def make_stack():
    session_provider = (
        FakeSessionProvider()
    )

    profile_provider = (
        FakeProfileProvider()
    )

    funds_provider = (
        FakeFundsProvider()
    )

    connectivity_provider = (
        FakeConnectivityProvider()
    )

    session_manager = (
        BrokerSessionManager(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            provider=session_provider,
            created_at=NOW,
        )
    )

    profile_service = (
        AccountProfileService(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            provider=profile_provider,
        )
    )

    funds_service = (
        AccountFundsService(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            provider=funds_provider,
        )
    )

    connectivity_monitor = (
        BrokerConnectivityMonitor(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            provider=(
                connectivity_provider
            ),
        )
    )

    registry = AccountStateRegistry()

    account_runtime = (
        AccountRuntimeService(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            session_manager=(
                session_manager
            ),
            profile_service=(
                profile_service
            ),
            funds_service=(
                funds_service
            ),
            connectivity_monitor=(
                connectivity_monitor
            ),
            eligibility_policy=(
                AccountTradingEligibilityPolicy()
            ),
            state_registry=registry,
        )
    )

    return {
        "session_manager":
            session_manager,

        "profile_provider":
            profile_provider,

        "funds_provider":
            funds_provider,

        "connectivity_provider":
            connectivity_provider,

        "registry":
            registry,

        "account_runtime":
            account_runtime,
    }


def make_runtime():
    bus = RuntimeEventBus()

    runtime = (
        TradingRuntimeOrchestrator(
            runtime_id=RuntimeId(
                "M08-M09-RUNTIME"
            ),
            trading_date=TODAY,
            mode=RuntimeMode.DRY_RUN,
            event_bus=bus,
            created_at=NOW,
        )
    )

    runtime.start(
        started_at=NOW
    )

    return runtime


# ============================================================
# Account initialization
# ============================================================


def test_account_runtime_registers_account():
    stack = make_stack()

    stack[
        "account_runtime"
    ].ensure_registered(
        registered_at=NOW
    )

    assert (
        stack["registry"].contains(
            ACCOUNT_ID
        )
        is True
    )


def test_account_registration_is_repeatable():
    stack = make_stack()

    first = stack[
        "account_runtime"
    ].ensure_registered(
        registered_at=NOW
    )

    second = stack[
        "account_runtime"
    ].ensure_registered(
        registered_at=NOW
    )

    assert first == second


# ============================================================
# Healthy startup
# ============================================================


def test_authenticated_account_refresh_is_healthy():
    stack = make_stack()

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    result = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        result.health.status
        is AccountHealthStatus.HEALTHY
    )

    assert (
        result.new_entries_allowed
        is True
    )


def test_refresh_populates_complete_registry_state():
    stack = make_stack()

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    result = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    state = result.account_state

    assert state.session is not None
    assert state.profile is not None
    assert state.funds is not None

    assert (
        state.connectivity
        is not None
    )

    assert state.health is not None

    assert (
        state.eligibility
        is not None
    )


# ============================================================
# M08 runtime interaction
# ============================================================


def test_m08_ready_runtime_can_be_account_validated_before_run():
    stack = make_stack()

    runtime = make_runtime()

    assert (
        runtime.state
        is RuntimeState.READY
    )

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    result = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        result.new_entries_allowed
        is True
    )

    runtime.run(
        running_at=NOW
    )

    assert (
        runtime.state
        is RuntimeState.RUNNING
    )


def test_account_block_can_prevent_application_from_running_runtime():
    stack = make_stack()

    runtime = make_runtime()

    # Session deliberately not authenticated.
    result = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        result.new_entries_allowed
        is False
    )

    # Application wiring must not call runtime.run()
    # when account readiness is blocked.
    assert (
        runtime.state
        is RuntimeState.READY
    )


# ============================================================
# Connectivity failure
# ============================================================


def test_disconnected_broker_marks_account_unhealthy():
    stack = make_stack()

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    stack[
        "connectivity_provider"
    ].connected = False

    result = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        result.health.status
        is AccountHealthStatus.UNHEALTHY
    )

    assert (
        result.new_entries_allowed
        is False
    )


# ============================================================
# Profile failure
# ============================================================


def test_profile_fetch_failure_degrades_health_and_blocks_entry():
    stack = make_stack()

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    stack[
        "profile_provider"
    ].error = RuntimeError(
        "profile unavailable"
    )

    result = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        result.health.status
        is AccountHealthStatus.DEGRADED
    )

    assert (
        result.new_entries_allowed
        is False
    )


# ============================================================
# Funds failure
# ============================================================


def test_funds_fetch_failure_degrades_health_and_blocks_entry():
    stack = make_stack()

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    stack[
        "funds_provider"
    ].error = RuntimeError(
        "funds unavailable"
    )

    result = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        result.health.status
        is AccountHealthStatus.DEGRADED
    )

    assert (
        result.new_entries_allowed
        is False
    )


def test_insufficient_funds_blocks_new_entry():
    stack = make_stack()

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    stack[
        "funds_provider"
    ].cash = Decimal(
        "5000"
    )

    result = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        result.health.status
        is AccountHealthStatus.HEALTHY
    )

    assert (
        result.new_entries_allowed
        is False
    )


# ============================================================
# Stale last-known-good data
# ============================================================


def test_failed_second_profile_refresh_does_not_treat_stale_data_as_current():
    stack = make_stack()

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    first = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        first.new_entries_allowed
        is True
    )

    stack[
        "profile_provider"
    ].error = RuntimeError(
        "profile refresh failed"
    )

    second = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        second.account_state.profile
        is not None
    )

    assert (
        second.health.profile_available
        is False
    )


def test_failed_second_funds_refresh_does_not_treat_stale_data_as_current():
    stack = make_stack()

    stack[
        "session_manager"
    ].authenticate(
        requested_at=NOW
    )

    first = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        first.new_entries_allowed
        is True
    )

    stack[
        "funds_provider"
    ].error = RuntimeError(
        "funds refresh failed"
    )

    second = stack[
        "account_runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    assert (
        second.account_state.funds
        is not None
    )

    assert (
        second.health.funds_available
        is False
    )