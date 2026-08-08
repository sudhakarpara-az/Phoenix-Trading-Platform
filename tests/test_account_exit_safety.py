"""
Phoenix M09-T13 Exit Safety Semantics tests.

Proves that M09 NEW-ENTRY restrictions do not suppress
protective M06 SELL execution.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.account.account_types import (
    AccountEligibilityReason,
    AccountTradingEligibility,
    BrokerAccountId,
    BrokerType,
)
from src.account.exit_safety import (
    ProtectiveExitSafetyService,
)


NOW = datetime(
    2026,
    8,
    8,
    13,
    0,
)

ACCOUNT_ID = BrokerAccountId(
    "DHAN-001"
)


class FakeExitExecution:
    def __init__(
        self,
    ):
        self.calls = []

        self.result = {
            "order_intent_id":
                "EXIT-001",
            "side":
                "SELL",
        }

        self.error = None

    def execute_exit(
        self,
        exit_decision,
        *,
        dry_run,
        requested_at,
    ):
        self.calls.append(
            {
                "exit_decision":
                    exit_decision,

                "dry_run":
                    dry_run,

                "requested_at":
                    requested_at,
            }
        )

        if self.error is not None:
            raise self.error

        return self.result


def make_service():
    execution = FakeExitExecution()

    service = ProtectiveExitSafetyService(
        broker=BrokerType.DHAN,
        account_id=ACCOUNT_ID,
        exit_execution=execution,
    )

    return (
        service,
        execution,
    )


def blocked(
    reason,
):
    return (
        AccountTradingEligibility
        .block(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            reason=reason,
            evaluated_at=NOW,
            available_cash=Decimal(
                "5000"
            ),
            required_cash=Decimal(
                "6500"
            ),
        )
    )


def allowed():
    return (
        AccountTradingEligibility
        .allow(
            broker=BrokerType.DHAN,
            account_id=ACCOUNT_ID,
            evaluated_at=NOW,
            available_cash=Decimal(
                "100000"
            ),
            required_cash=Decimal(
                "6500"
            ),
        )
    )


# ============================================================
# Basic protective exit
# ============================================================


def test_protective_exit_executes():
    service, execution = (
        make_service()
    )

    result = service.execute_exit(
        "STOP-LOSS",
        dry_run=True,
        requested_at=NOW,
    )

    assert result.executed is True

    assert (
        len(execution.calls)
        == 1
    )


def test_exit_arguments_forwarded_unchanged():
    service, execution = (
        make_service()
    )

    service.execute_exit(
        "TARGET-EXIT",
        dry_run=False,
        requested_at=NOW,
    )

    call = execution.calls[0]

    assert (
        call["exit_decision"]
        == "TARGET-EXIT"
    )

    assert (
        call["dry_run"]
        is False
    )

    assert (
        call["requested_at"]
        == NOW
    )


# ============================================================
# Allowed account
# ============================================================


def test_allowed_account_exit_executes():
    service, execution = (
        make_service()
    )

    result = service.execute_exit(
        "TARGET",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            allowed()
        ),
    )

    assert result.executed is True

    assert (
        len(execution.calls)
        == 1
    )


# ============================================================
# BUY restrictions MUST NOT block SELL
# ============================================================


@pytest.mark.parametrize(
    "reason",
    [
        AccountEligibilityReason
        .ACCOUNT_STATUS_UNKNOWN,

        AccountEligibilityReason
        .ACCOUNT_INACTIVE,

        AccountEligibilityReason
        .ACCOUNT_BLOCKED,

        AccountEligibilityReason
        .TRADING_NOT_ENABLED,

        AccountEligibilityReason
        .SESSION_NOT_AUTHENTICATED,

        AccountEligibilityReason
        .SESSION_EXPIRED,

        AccountEligibilityReason
        .SESSION_FAILED,

        AccountEligibilityReason
        .BROKER_UNAVAILABLE,

        AccountEligibilityReason
        .PROFILE_UNAVAILABLE,

        AccountEligibilityReason
        .FUNDS_UNAVAILABLE,

        AccountEligibilityReason
        .INSUFFICIENT_FUNDS,
    ],
)
def test_blocked_entry_reason_does_not_veto_exit(
    reason,
):
    service, execution = (
        make_service()
    )

    result = service.execute_exit(
        "PROTECTIVE-SELL",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            blocked(
                reason
            )
        ),
    )

    assert result.executed is True

    assert (
        len(execution.calls)
        == 1
    )

    assert (
        result
        .account_eligibility
        .allowed
        is False
    )

    assert (
        result
        .account_eligibility
        .reason
        is reason
    )


# ============================================================
# Specific exit types
# ============================================================


def test_insufficient_funds_does_not_block_target_exit():
    service, execution = (
        make_service()
    )

    service.execute_exit(
        "TARGET",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            blocked(
                AccountEligibilityReason
                .INSUFFICIENT_FUNDS
            )
        ),
    )

    assert (
        len(execution.calls)
        == 1
    )


def test_account_blocked_does_not_block_stop_loss():
    service, execution = (
        make_service()
    )

    service.execute_exit(
        "STOP_LOSS",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            blocked(
                AccountEligibilityReason
                .ACCOUNT_BLOCKED
            )
        ),
    )

    assert (
        len(execution.calls)
        == 1
    )


def test_expired_session_does_not_suppress_force_exit():
    service, execution = (
        make_service()
    )

    service.execute_exit(
        "FORCE_EXIT_1515",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            blocked(
                AccountEligibilityReason
                .SESSION_EXPIRED
            )
        ),
    )

    assert (
        len(execution.calls)
        == 1
    )


def test_profile_unavailable_does_not_block_sell():
    service, execution = (
        make_service()
    )

    service.execute_exit(
        "STOP_LOSS",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            blocked(
                AccountEligibilityReason
                .PROFILE_UNAVAILABLE
            )
        ),
    )

    assert (
        len(execution.calls)
        == 1
    )


def test_funds_unavailable_does_not_block_sell():
    service, execution = (
        make_service()
    )

    service.execute_exit(
        "TARGET",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            blocked(
                AccountEligibilityReason
                .FUNDS_UNAVAILABLE
            )
        ),
    )

    assert (
        len(execution.calls)
        == 1
    )


# ============================================================
# Broker/M06 failure propagation
# ============================================================


def test_exit_execution_failure_is_not_swallowed():
    service, execution = (
        make_service()
    )

    execution.error = RuntimeError(
        "broker unavailable"
    )

    with pytest.raises(
        RuntimeError,
        match="broker unavailable",
    ):
        service.execute_exit(
            "STOP_LOSS",
            dry_run=False,
            requested_at=NOW,
            account_eligibility=(
                blocked(
                    AccountEligibilityReason
                    .BROKER_UNAVAILABLE
                )
            ),
        )

    # Critical distinction:
    # Phoenix ATTEMPTED the exit.
    assert (
        len(execution.calls)
        == 1
    )


def test_exit_execution_failure_does_not_create_success_attempt():
    service, execution = (
        make_service()
    )

    execution.error = RuntimeError(
        "sell rejected"
    )

    with pytest.raises(
        RuntimeError
    ):
        service.execute_exit(
            "STOP_LOSS",
            dry_run=False,
            requested_at=NOW,
        )

    assert (
        service.last_attempt
        is None
    )


# ============================================================
# Diagnostic state
# ============================================================


def test_successful_exit_records_last_attempt():
    service, _ = make_service()

    result = service.execute_exit(
        "TARGET",
        dry_run=True,
        requested_at=NOW,
    )

    assert (
        service.last_attempt
        == result
    )


def test_blocked_eligibility_is_preserved_for_audit():
    service, _ = make_service()

    eligibility = blocked(
        AccountEligibilityReason
        .ACCOUNT_BLOCKED
    )

    result = service.execute_exit(
        "STOP_LOSS",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=(
            eligibility
        ),
    )

    assert (
        result.account_eligibility
        == eligibility
    )


# ============================================================
# Identity safety
# ============================================================


def test_diagnostic_account_mismatch_rejected():
    service, execution = (
        make_service()
    )

    bad = (
        AccountTradingEligibility
        .block(
            broker=BrokerType.DHAN,
            account_id=(
                BrokerAccountId(
                    "OTHER"
                )
            ),
            reason=(
                AccountEligibilityReason
                .ACCOUNT_BLOCKED
            ),
            evaluated_at=NOW,
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit diagnostic eligibility "
            "account mismatch"
        ),
    ):
        service.execute_exit(
            "STOP_LOSS",
            dry_run=False,
            requested_at=NOW,
            account_eligibility=bad,
        )

    assert (
        execution.calls
        == []
    )


# ============================================================
# No eligibility required
# ============================================================


def test_exit_does_not_require_account_eligibility():
    service, execution = (
        make_service()
    )

    result = service.execute_exit(
        "FORCE_EXIT_1515",
        dry_run=False,
        requested_at=NOW,
        account_eligibility=None,
    )

    assert result.executed is True

    assert (
        len(execution.calls)
        == 1
    )