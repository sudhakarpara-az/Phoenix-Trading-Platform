"""
Phoenix M09-T16 Failure & Edge-Case Tests.

Stress-tests the integrated M09 broker/account-management layer.

Primary invariants:
    - uncertain broker/account state blocks NEW BUYs
    - stale state is never silently trusted
    - identity mismatches fail closed
    - repeated authentication failures remain blocked
    - broker outages do not become false-positive readiness
    - malformed broker payloads are rejected
    - insufficient funds is an eligibility failure, not a
      reconciliation failure
    - protective SELL attempts remain independent from
      new-entry eligibility
"""

from datetime import (
    datetime,
    timedelta,
)
from decimal import Decimal

import pytest

from src.account.account_eligibility_policy import (
    AccountTradingEligibilityPolicy,
)
from src.account.account_execution_gate import (
    AccountEntryBlockedError,
    AccountExecutionSafetyGate,
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
    AccountEligibilityReason,
    AccountFundsSnapshot,
    AccountProfile,
    AccountTradingEligibility,
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
    BrokerConnectivityCheckError,
    BrokerConnectivityMonitor,
    BrokerConnectivitySnapshot,
)
from src.account.dhan_account_adapter import (
    DhanAccountAdapter,
    DhanAccountAdapterError,
)
from src.account.exit_safety import (
    ProtectiveExitSafetyService,
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
    15,
    0,
)

LATER = (
    NOW
    + timedelta(minutes=1)
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)

OTHER_ACCOUNT = BrokerAccountId(
    "DHAN-OTHER"
)

REQUIRED_CASH = Decimal(
    "6500"
)


# ============================================================
# Shared fake providers
# ============================================================


class FakeSessionProvider:
    def __init__(
        self,
    ):
        self.error = None
        self.calls = 0

        self.result = (
            BrokerSessionSnapshot(
                broker=BrokerType.DHAN,
                account_id=ACCOUNT_ID,
                status=(
                    BrokerSessionStatus
                    .AUTHENTICATED
                ),
                authenticated_at=NOW,
                updated_at=NOW,
            )
        )

    def authenticate(
        self,
        *,
        broker,
        account_id,
        requested_at,
    ):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return self.result

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

        self.account_id = ACCOUNT_ID

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
            account_id=(
                self.account_id
            ),
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

        self.account_id = ACCOUNT_ID

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
            account_id=(
                self.account_id
            ),
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

        self.account_id = ACCOUNT_ID

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
            account_id=(
                self.account_id
            ),
            connected=self.connected,
            checked_at=checked_at,
            message=(
                None
                if self.connected
                else "broker disconnected"
            ),
        )


class FakeEntryExecution:
    def __init__(
        self,
    ):
        self.calls = []
        self.error = None

    def execute_entry(
        self,
        *,
        signal,
        selected_option,
        dry_run,
        requested_at,
    ):
        self.calls.append(
            (
                signal,
                selected_option,
                dry_run,
                requested_at,
            )
        )

        if self.error is not None:
            raise self.error

        return {
            "order_id": "BUY-001"
        }


class FakeExitExecution:
    def __init__(
        self,
    ):
        self.calls = []
        self.error = None

    def execute_exit(
        self,
        exit_decision,
        *,
        dry_run,
        requested_at,
    ):
        self.calls.append(
            (
                exit_decision,
                dry_run,
                requested_at,
            )
        )

        if self.error is not None:
            raise self.error

        return {
            "order_id": "SELL-001"
        }


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


# ============================================================
# Stack builder
# ============================================================


def make_stack(
    *,
    authenticate=True,
):
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

    if authenticate:
        session_manager.authenticate(
            requested_at=NOW
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

    entry_execution = (
        FakeEntryExecution()
    )

    entry_gate = (
        AccountExecutionSafetyGate(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            account_runtime=runtime,
            entry_execution=(
                entry_execution
            ),
        )
    )

    exit_execution = (
        FakeExitExecution()
    )

    exit_safety = (
        ProtectiveExitSafetyService(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            exit_execution=(
                exit_execution
            ),
        )
    )

    reauth = SessionReauthService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        session_manager=session_manager,
    )

    persisted = (
        FakePersistedStateProvider()
    )

    reconciliation = (
        AccountReconciliationService(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            persisted_state=(
                persisted
            ),
            session_reauth=reauth,
            account_runtime=runtime,
            state_registry=registry,
        )
    )

    return {
        "session_provider":
            session_provider,

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

        "runtime":
            runtime,

        "entry_execution":
            entry_execution,

        "entry_gate":
            entry_gate,

        "exit_execution":
            exit_execution,

        "exit_safety":
            exit_safety,

        "reauth":
            reauth,

        "persisted":
            persisted,

        "reconciliation":
            reconciliation,
    }


# ============================================================
# Identity mismatch safety
# ============================================================


def test_profile_identity_mismatch_blocks_new_entry():
    stack = make_stack()

    stack[
        "profile_provider"
    ].account_id = OTHER_ACCOUNT

    with pytest.raises(
        AccountEntryBlockedError
    ):
        stack[
            "entry_gate"
        ].execute_entry(
            signal="SIGNAL",
            selected_option="OPTION",
            required_cash=(
                REQUIRED_CASH
            ),
            dry_run=False,
            requested_at=NOW,
        )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


def test_funds_identity_mismatch_blocks_new_entry():
    stack = make_stack()

    stack[
        "funds_provider"
    ].account_id = OTHER_ACCOUNT

    with pytest.raises(
        AccountEntryBlockedError
    ):
        stack[
            "entry_gate"
        ].execute_entry(
            signal="SIGNAL",
            selected_option="OPTION",
            required_cash=(
                REQUIRED_CASH
            ),
            dry_run=False,
            requested_at=NOW,
        )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


def test_connectivity_identity_mismatch_blocks_new_entry():
    stack = make_stack()

    stack[
        "connectivity_provider"
    ].account_id = OTHER_ACCOUNT

    with pytest.raises(
        AccountEntryBlockedError
    ):
        stack[
            "entry_gate"
        ].execute_entry(
            signal="SIGNAL",
            selected_option="OPTION",
            required_cash=(
                REQUIRED_CASH
            ),
            dry_run=False,
            requested_at=NOW,
        )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


# ============================================================
# Repeated authentication failure
# ============================================================


def test_repeated_reauth_failures_remain_blocked():
    stack = make_stack(
        authenticate=False
    )

    stack[
        "session_provider"
    ].error = RuntimeError(
        "authentication unavailable"
    )

    first = stack[
        "reauth"
    ].ensure_authenticated(
        checked_at=NOW
    )

    second = stack[
        "reauth"
    ].ensure_authenticated(
        checked_at=LATER
    )

    assert (
        first.authenticated
        is False
    )

    assert (
        second.authenticated
        is False
    )

    assert (
        stack[
            "session_manager"
        ].status
        is BrokerSessionStatus.FAILED
    )


# ============================================================
# Stale state safety
# ============================================================


def test_last_good_profile_does_not_override_failed_refresh():
    stack = make_stack()

    first = stack[
        "runtime"
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
        "runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=LATER,
    )

    assert (
        second.account_state.profile
        is not None
    )

    assert (
        second.health.profile_available
        is False
    )


def test_last_good_funds_do_not_override_failed_refresh():
    stack = make_stack()

    first = stack[
        "runtime"
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
        "runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=LATER,
    )

    assert (
        second.account_state.funds
        is not None
    )

    assert (
        second.health.funds_available
        is False
    )


# ============================================================
# Broker outage / reconnect
# ============================================================


def test_broker_outage_blocks_new_entry():
    stack = make_stack()

    stack[
        "connectivity_provider"
    ].connected = False

    with pytest.raises(
        AccountEntryBlockedError
    ) as exc:
        stack[
            "entry_gate"
        ].execute_entry(
            signal="SIGNAL",
            selected_option="OPTION",
            required_cash=(
                REQUIRED_CASH
            ),
            dry_run=False,
            requested_at=NOW,
        )

    assert (
        exc.value.eligibility.reason
        is AccountEligibilityReason
        .BROKER_UNAVAILABLE
    )


def test_reconnect_restores_entry_after_successful_refresh():
    stack = make_stack()

    stack[
        "connectivity_provider"
    ].connected = False

    with pytest.raises(
        AccountEntryBlockedError
    ):
        stack[
            "entry_gate"
        ].execute_entry(
            signal="SIGNAL",
            selected_option="OPTION",
            required_cash=(
                REQUIRED_CASH
            ),
            dry_run=False,
            requested_at=NOW,
        )

    stack[
        "connectivity_provider"
    ].connected = True

    result = stack[
        "entry_gate"
    ].execute_entry(
        signal="SIGNAL",
        selected_option="OPTION",
        required_cash=(
            REQUIRED_CASH
        ),
        dry_run=True,
        requested_at=LATER,
    )

    assert (
        result.executed
        is True
    )


# ============================================================
# Zero funds / exact funds
# ============================================================


def test_zero_available_cash_blocks_positive_cost_entry():
    stack = make_stack()

    stack[
        "funds_provider"
    ].cash = Decimal(
        "0"
    )

    with pytest.raises(
        AccountEntryBlockedError
    ) as exc:
        stack[
            "entry_gate"
        ].execute_entry(
            signal="SIGNAL",
            selected_option="OPTION",
            required_cash=Decimal(
                "1"
            ),
            dry_run=False,
            requested_at=NOW,
        )

    assert (
        exc.value.eligibility.reason
        is AccountEligibilityReason
        .INSUFFICIENT_FUNDS
    )


def test_exact_available_cash_is_allowed():
    stack = make_stack()

    stack[
        "funds_provider"
    ].cash = (
        REQUIRED_CASH
    )

    result = stack[
        "entry_gate"
    ].execute_entry(
        signal="SIGNAL",
        selected_option="OPTION",
        required_cash=(
            REQUIRED_CASH
        ),
        dry_run=True,
        requested_at=NOW,
    )

    assert (
        result.executed
        is True
    )


# ============================================================
# Duplicate refresh behavior
# ============================================================


def test_repeated_runtime_refreshes_do_not_duplicate_account_registration():
    stack = make_stack()

    stack[
        "runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=NOW,
    )

    stack[
        "runtime"
    ].refresh(
        required_cash=(
            REQUIRED_CASH
        ),
        refreshed_at=LATER,
    )

    assert (
        len(
            stack[
                "registry"
            ].accounts()
        )
        == 1
    )


# ============================================================
# Reconciliation edge cases
# ============================================================


def test_missing_persisted_account_fails_closed():
    stack = make_stack(
        authenticate=False
    )

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

    assert (
        result.completed
        is False
    )

    assert (
        result.new_entries_allowed
        is False
    )


def test_reconciliation_identity_mismatch_fails_before_live_refresh():
    stack = make_stack(
        authenticate=False
    )

    stack[
        "persisted"
    ].result = (
        PersistedBrokerAccountState(
            broker=BrokerType.DHAN,
            account_id=OTHER_ACCOUNT,
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

    assert (
        result.completed
        is False
    )

    assert (
        AccountReconciliationIssueCode
        .ACCOUNT_ID_MISMATCH
        in {
            issue.code
            for issue
            in result.issues
        }
    )


def test_insufficient_funds_does_not_make_reconciliation_fail():
    stack = make_stack(
        authenticate=False
    )

    stack[
        "funds_provider"
    ].cash = Decimal(
        "1"
    )

    result = stack[
        "reconciliation"
    ].reconcile(
        required_cash=(
            REQUIRED_CASH
        ),
        reconciled_at=NOW,
    )

    assert (
        result.completed
        is True
    )

    assert (
        result.new_entries_allowed
        is False
    )


# ============================================================
# Exit-path safety
# ============================================================


@pytest.mark.parametrize(
    "reason",
    [
        AccountEligibilityReason
        .INSUFFICIENT_FUNDS,

        AccountEligibilityReason
        .ACCOUNT_BLOCKED,

        AccountEligibilityReason
        .ACCOUNT_INACTIVE,

        AccountEligibilityReason
        .SESSION_EXPIRED,

        AccountEligibilityReason
        .BROKER_UNAVAILABLE,

        AccountEligibilityReason
        .PROFILE_UNAVAILABLE,

        AccountEligibilityReason
        .FUNDS_UNAVAILABLE,
    ],
)
def test_entry_block_reasons_do_not_suppress_exit(
    reason,
):
    stack = make_stack()

    eligibility = (
        AccountTradingEligibility
        .block(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            reason=reason,
            evaluated_at=NOW,
        )
    )

    result = stack[
        "exit_safety"
    ].execute_exit(
        "STOP_LOSS",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            eligibility
        ),
    )

    assert (
        result.executed
        is True
    )

    assert (
        len(
            stack[
                "exit_execution"
            ].calls
        )
        == 1
    )


def test_exit_broker_failure_is_visible():
    stack = make_stack()

    stack[
        "exit_execution"
    ].error = RuntimeError(
        "broker unavailable"
    )

    with pytest.raises(
        RuntimeError,
        match="broker unavailable",
    ):
        stack[
            "exit_safety"
        ].execute_exit(
            "FORCE_EXIT_1515",
            dry_run=False,
            requested_at=NOW,
        )

    assert (
        len(
            stack[
                "exit_execution"
            ].calls
        )
        == 1
    )


# ============================================================
# Dhan adapter malformed payloads
# ============================================================


class FakeDhanClient:
    def __init__(
        self,
        response,
    ):
        self.response = response

    def get_fund_limits(
        self,
    ):
        return self.response


def profile_fetcher(
    payload,
):
    return lambda: payload


def test_dhan_non_dict_fund_response_rejected():
    adapter = DhanAccountAdapter(
        dhan_client=(
            FakeDhanClient(
                response="invalid"
            )
        ),
        profile_fetcher=(
            profile_fetcher(
                {
                    "dhanClientId":
                        ACCOUNT_ID.value,

                    "activeSegment":
                        "Derivative",
                }
            )
        ),
        account_id=ACCOUNT_ID,
    )

    with pytest.raises(
        DhanAccountAdapterError
    ):
        adapter.fetch_funds(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


def test_dhan_missing_client_id_rejected():
    adapter = DhanAccountAdapter(
        dhan_client=(
            FakeDhanClient(
                response={
                    "availabelBalance": 1000,
                    "sodLimit": 1000,
                    "collateralAmount": 0,
                    "utilizedAmount": 0,
                }
            )
        ),
        profile_fetcher=(
            profile_fetcher(
                {
                    "activeSegment":
                        "Derivative",
                }
            )
        ),
        account_id=ACCOUNT_ID,
    )

    with pytest.raises(
        DhanAccountAdapterError,
        match="missing dhanClientId",
    ):
        adapter.fetch_profile(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )


def test_dhan_invalid_numeric_field_rejected():
    adapter = DhanAccountAdapter(
        dhan_client=(
            FakeDhanClient(
                response={
                    "dhanClientId":
                        ACCOUNT_ID.value,

                    "availabelBalance":
                        "not-a-number",

                    "sodLimit":
                        1000,

                    "collateralAmount":
                        0,

                    "utilizedAmount":
                        0,
                }
            )
        ),
        profile_fetcher=(
            profile_fetcher(
                {
                    "dhanClientId":
                        ACCOUNT_ID.value,

                    "activeSegment":
                        "Derivative",
                }
            )
        ),
        account_id=ACCOUNT_ID,
    )

    with pytest.raises(
        DhanAccountAdapterError,
        match=(
            "invalid availabelBalance"
        ),
    ):
        adapter.fetch_funds(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            requested_at=NOW,
        )