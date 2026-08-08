"""
Phoenix M09-T12 M09 -> M06 Execution Safety Gate tests.
"""

from datetime import datetime
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


NOW = datetime(
    2026,
    8,
    8,
    12,
    30,
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)

REQUIRED_CASH = Decimal(
    "6500"
)


# ============================================================
# Fake M06 execution
# ============================================================


class FakeEntryExecution:
    def __init__(
        self,
    ):
        self.calls = []

        self.result = {
            "order_intent_id":
                "ORD-ENTRY-001"
        }

    def execute_entry(
        self,
        *,
        signal,
        selected_option,
        dry_run,
        requested_at,
    ):
        self.calls.append(
            {
                "signal": signal,
                "selected_option":
                    selected_option,
                "dry_run": dry_run,
                "requested_at":
                    requested_at,
            }
        )

        return self.result


# ============================================================
# M09 fake providers
# ============================================================


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
        self.status = (
            BrokerAccountStatus.ACTIVE
        )

        self.trading_enabled = True

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
        self.cash = Decimal(
            "100000"
        )

        self.error = None

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


# ============================================================
# Fixture builder
# ============================================================


def make_gate(
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

    entry_execution = (
        FakeEntryExecution()
    )

    gate = (
        AccountExecutionSafetyGate(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            account_runtime=(
                account_runtime
            ),
            entry_execution=(
                entry_execution
            ),
        )
    )

    return {
        "gate": gate,
        "entry_execution":
            entry_execution,
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
    }


# ============================================================
# Allowed execution
# ============================================================


def test_allowed_account_executes_m06_entry():
    stack = make_gate()

    result = stack[
        "gate"
    ].execute_entry(
        signal="SIGNAL",
        selected_option="OPTION",
        required_cash=(
            REQUIRED_CASH
        ),
        dry_run=True,
        requested_at=NOW,
    )

    assert result.executed is True
    assert result.blocked is False

    assert (
        result.eligibility.allowed
        is True
    )

    assert (
        len(
            stack[
                "entry_execution"
            ].calls
        )
        == 1
    )


def test_allowed_entry_forwards_m06_arguments():
    stack = make_gate()

    stack[
        "gate"
    ].execute_entry(
        signal="SIGNAL-001",
        selected_option="OPTION-001",
        required_cash=(
            REQUIRED_CASH
        ),
        dry_run=True,
        requested_at=NOW,
    )

    call = stack[
        "entry_execution"
    ].calls[0]

    assert (
        call["signal"]
        == "SIGNAL-001"
    )

    assert (
        call["selected_option"]
        == "OPTION-001"
    )

    assert (
        call["dry_run"]
        is True
    )

    assert (
        call["requested_at"]
        == NOW
    )


def test_live_flag_is_forwarded_to_m06():
    stack = make_gate()

    stack[
        "gate"
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
        ].calls[0]["dry_run"]
        is False
    )


# ============================================================
# Session gate
# ============================================================


def test_unauthenticated_session_blocks_before_m06():
    stack = make_gate(
        authenticate=False
    )

    with pytest.raises(
        AccountEntryBlockedError
    ) as exc:
        stack[
            "gate"
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
        .SESSION_NOT_AUTHENTICATED
    )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


# ============================================================
# Connectivity gate
# ============================================================


def test_disconnected_broker_blocks_before_m06():
    stack = make_gate()

    stack[
        "connectivity_provider"
    ].connected = False

    with pytest.raises(
        AccountEntryBlockedError
    ) as exc:
        stack[
            "gate"
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

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


# ============================================================
# Profile gate
# ============================================================


def test_blocked_account_stops_m06_entry():
    stack = make_gate()

    stack[
        "profile_provider"
    ].status = (
        BrokerAccountStatus.BLOCKED
    )

    with pytest.raises(
        AccountEntryBlockedError
    ) as exc:
        stack[
            "gate"
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
        .ACCOUNT_BLOCKED
    )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


def test_trading_disabled_stops_m06_entry():
    stack = make_gate()

    stack[
        "profile_provider"
    ].trading_enabled = False

    with pytest.raises(
        AccountEntryBlockedError
    ) as exc:
        stack[
            "gate"
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
        .TRADING_NOT_ENABLED
    )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


# ============================================================
# Funds gate
# ============================================================


def test_insufficient_funds_stops_m06_entry():
    stack = make_gate()

    stack[
        "funds_provider"
    ].cash = Decimal(
        "5000"
    )

    with pytest.raises(
        AccountEntryBlockedError
    ) as exc:
        stack[
            "gate"
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
        .INSUFFICIENT_FUNDS
    )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


def test_exact_required_cash_allows_entry():
    stack = make_gate()

    stack[
        "funds_provider"
    ].cash = (
        REQUIRED_CASH
    )

    result = stack[
        "gate"
    ].execute_entry(
        signal="SIGNAL",
        selected_option="OPTION",
        required_cash=(
            REQUIRED_CASH
        ),
        dry_run=True,
        requested_at=NOW,
    )

    assert result.executed is True


def test_negative_required_cash_rejected_before_m06():
    stack = make_gate()

    with pytest.raises(
        ValueError,
        match=(
            "required cash cannot be negative"
        ),
    ):
        stack[
            "gate"
        ].execute_entry(
            signal="SIGNAL",
            selected_option="OPTION",
            required_cash=Decimal(
                "-1"
            ),
            dry_run=True,
            requested_at=NOW,
        )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )


# ============================================================
# Fetch failure safety
# ============================================================


def test_profile_refresh_failure_blocks_before_m06():
    stack = make_gate()

    stack[
        "profile_provider"
    ].error = RuntimeError(
        "profile unavailable"
    )

    with pytest.raises(
        AccountEntryBlockedError
    ):
        stack[
            "gate"
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


def test_funds_refresh_failure_blocks_before_m06():
    stack = make_gate()

    stack[
        "funds_provider"
    ].error = RuntimeError(
        "funds unavailable"
    )

    with pytest.raises(
        AccountEntryBlockedError
    ):
        stack[
            "gate"
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
# State / audit visibility
# ============================================================


def test_gate_retains_last_allowed_result():
    stack = make_gate()

    result = stack[
        "gate"
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
        stack[
            "gate"
        ].last_result
        == result
    )

    assert (
        stack[
            "gate"
        ].last_eligibility.allowed
        is True
    )


def test_gate_retains_blocked_eligibility():
    stack = make_gate()

    stack[
        "funds_provider"
    ].cash = Decimal(
        "1"
    )

    with pytest.raises(
        AccountEntryBlockedError
    ):
        stack[
            "gate"
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
            "gate"
        ].last_result.blocked
        is True
    )

    assert (
        stack[
            "gate"
        ].last_eligibility.reason
        is AccountEligibilityReason
        .INSUFFICIENT_FUNDS
    )


def test_account_registry_is_refreshed_before_execution():
    stack = make_gate()

    stack[
        "gate"
    ].execute_entry(
        signal="SIGNAL",
        selected_option="OPTION",
        required_cash=(
            REQUIRED_CASH
        ),
        dry_run=True,
        requested_at=NOW,
    )

    state = stack[
        "registry"
    ].require(
        ACCOUNT_ID
    )

    assert state.session is not None
    assert state.profile is not None
    assert state.funds is not None

    assert (
        state.connectivity
        is not None
    )

    assert (
        state.eligibility
        is not None
    )

    assert (
        state.eligibility.allowed
        is True
    )


# ============================================================
# Evaluation without execution
# ============================================================


def test_evaluate_only_does_not_call_m06():
    stack = make_gate()

    result = stack[
        "gate"
    ].evaluate_only(
        required_cash=(
            REQUIRED_CASH
        ),
        evaluated_at=NOW,
    )

    assert (
        result.new_entries_allowed
        is True
    )

    assert (
        stack[
            "entry_execution"
        ].calls
        == []
    )