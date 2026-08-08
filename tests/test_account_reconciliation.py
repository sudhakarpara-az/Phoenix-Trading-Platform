"""
Phoenix M09-T15 Broker / Account Reconciliation tests.
"""

from datetime import datetime
from decimal import Decimal

from src.account.account_eligibility_policy import (
    AccountTradingEligibilityPolicy,
)
from src.account.account_profile_provider import (
    AccountProfileService,
)
from src.account.account_reconciliation import (
    AccountReconciliationIssueCode,
    AccountReconciliationService,
    PersistedBrokerAccountState,
)
from src.account.account_runtime_service import (
    AccountRuntimeService,
)
from src.account.account_state_registry import (
    AccountStateRegistry,
)
from src.account.account_types import (
    AccountFundsSnapshot,
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
from src.account.session_reauth_service import (
    SessionReauthService,
)


NOW = datetime(
    2026,
    8,
    8,
    14,
    0,
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)

REQUIRED_CASH = Decimal(
    "6500"
)


class FakePersistedStateProvider:
    def __init__(
        self,
    ):
        self.result = (
            PersistedBrokerAccountState(
                broker=BrokerType.DHAN,
                account_id=ACCOUNT_ID,
            )
        )

    def load_account(
        self,
        *,
        broker,
        account_id,
    ):
        del broker
        del account_id

        return self.result


class FakeSessionProvider:
    def __init__(
        self,
    ):
        self.error = None

    def authenticate(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        if self.error is not None:
            raise self.error

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
            updated_at=requested_at,
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

        self.status = (
            BrokerAccountStatus.ACTIVE
        )

        self.trading_enabled = True

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
            account_status=self.status,
            fetched_at=requested_at,
            trading_enabled=(
                self.trading_enabled
            ),
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
            fetched_at=requested_at,
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
                else "broker disconnected"
            ),
        )


def make_stack():
    persisted = (
        FakePersistedStateProvider()
    )

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

    reauth = SessionReauthService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        session_manager=session_manager,
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

    runtime = AccountRuntimeService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        session_manager=session_manager,
        profile_service=profile_service,
        funds_service=funds_service,
        connectivity_monitor=(
            connectivity_monitor
        ),
        eligibility_policy=(
            AccountTradingEligibilityPolicy()
        ),
        state_registry=registry,
    )

    reconciliation = (
        AccountReconciliationService(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            persisted_state=persisted,
            session_reauth=reauth,
            account_runtime=runtime,
            state_registry=registry,
        )
    )

    return {
        "persisted": persisted,
        "session_provider":
            session_provider,
        "profile_provider":
            profile_provider,
        "funds_provider":
            funds_provider,
        "connectivity_provider":
            connectivity_provider,
        "registry": registry,
        "reconciliation":
            reconciliation,
    }


def issue_codes(
    result,
):
    return {
        issue.code
        for issue in result.issues
    }


# ============================================================
# Healthy recovery
# ============================================================


def test_reconciliation_success():
    stack = make_stack()

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is True

    assert (
        result.new_entries_allowed
        is True
    )

    assert result.issues == ()


def test_success_restores_registry():
    stack = make_stack()

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    state = stack[
        "registry"
    ].require(
        ACCOUNT_ID
    )

    assert result.completed is True

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
# Persistence identity
# ============================================================


def test_missing_persisted_account_blocks_reconciliation():
    stack = make_stack()

    stack[
        "persisted"
    ].result = None

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .ACCOUNT_NOT_PERSISTED
        in issue_codes(result)
    )


def test_persisted_account_mismatch_blocks_reconciliation():
    stack = make_stack()

    stack[
        "persisted"
    ].result = (
        PersistedBrokerAccountState(
            broker=BrokerType.DHAN,
            account_id=(
                BrokerAccountId(
                    "OTHER"
                )
            ),
        )
    )

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .ACCOUNT_ID_MISMATCH
        in issue_codes(result)
    )


# ============================================================
# Session recovery
# ============================================================


def test_session_recovery_failure_blocks_reconciliation():
    stack = make_stack()

    stack[
        "session_provider"
    ].error = RuntimeError(
        "authentication unavailable"
    )

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .SESSION_RECOVERY_FAILED
        in issue_codes(result)
    )


# ============================================================
# Connectivity
# ============================================================


def test_disconnected_broker_blocks_reconciliation():
    stack = make_stack()

    stack[
        "connectivity_provider"
    ].connected = False

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .BROKER_UNAVAILABLE
        in issue_codes(result)
    )


# ============================================================
# Profile
# ============================================================


def test_profile_failure_blocks_reconciliation():
    stack = make_stack()

    stack[
        "profile_provider"
    ].error = RuntimeError(
        "profile unavailable"
    )

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .PROFILE_UNAVAILABLE
        in issue_codes(result)
    )


def test_blocked_account_blocks_reconciliation():
    stack = make_stack()

    stack[
        "profile_provider"
    ].status = (
        BrokerAccountStatus.BLOCKED
    )

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .ACCOUNT_BLOCKED
        in issue_codes(result)
    )


def test_inactive_account_blocks_reconciliation():
    stack = make_stack()

    stack[
        "profile_provider"
    ].status = (
        BrokerAccountStatus.INACTIVE
    )

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .ACCOUNT_INACTIVE
        in issue_codes(result)
    )


def test_trading_disabled_blocks_reconciliation():
    stack = make_stack()

    stack[
        "profile_provider"
    ].trading_enabled = False

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .TRADING_NOT_ENABLED
        in issue_codes(result)
    )


# ============================================================
# Funds
# ============================================================


def test_funds_failure_blocks_reconciliation():
    stack = make_stack()

    stack[
        "funds_provider"
    ].error = RuntimeError(
        "funds unavailable"
    )

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is False

    assert (
        AccountReconciliationIssueCode
        .FUNDS_UNAVAILABLE
        in issue_codes(result)
    )


def test_insufficient_funds_is_not_reconciliation_failure():
    stack = make_stack()

    stack[
        "funds_provider"
    ].cash = Decimal(
        "5000"
    )

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert result.completed is True

    assert (
        result.new_entries_allowed
        is False
    )

    assert result.issues == ()


# ============================================================
# Validation
# ============================================================


def test_negative_required_cash_rejected():
    stack = make_stack()

    try:
        stack[
            "reconciliation"
        ].reconcile(
            required_cash=Decimal(
                "-1"
            ),
            reconciled_at=NOW,
        )

    except ValueError as exc:
        assert (
            str(exc)
            == (
                "required cash "
                "cannot be negative"
            )
        )

    else:
        raise AssertionError(
            "ValueError expected"
        )