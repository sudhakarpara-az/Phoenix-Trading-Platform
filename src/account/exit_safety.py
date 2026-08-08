"""
Phoenix M09 Exit Safety Semantics.

Protective exits for existing positions must remain independent
from M09 NEW-ENTRY eligibility.

Responsibilities:
    - provide a narrow wrapper around M06 exit execution
    - preserve account/broker identity for diagnostics
    - record latest exit-attempt result
    - never apply AccountTradingEligibility as an exit veto
    - propagate M06/broker execution failures unchanged

This module does NOT:
    - decide TARGET / STOP / FORCE_EXIT
    - calculate exit prices
    - calculate account eligibility
    - refresh funds/profile
    - convert BUY restrictions into SELL restrictions

M07 decides whether an exit is required.
M06 remains responsible for executing the SELL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import (
    Any,
    Protocol,
)

from src.account.account_types import (
    AccountTradingEligibility,
    BrokerAccountId,
    BrokerType,
)


class ProtectiveExitExecutionProvider(
    Protocol,
):
    """
    Existing M06 exit-execution boundary.
    """

    def execute_exit(
        self,
        exit_decision: Any,
        *,
        dry_run: bool,
        requested_at: datetime,
    ) -> Any:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class ProtectiveExitAttempt:
    """
    Audit-friendly result of one protective exit attempt.

    account_eligibility is informational only and never acts
    as an exit veto.
    """

    broker: BrokerType

    account_id: BrokerAccountId

    exit_decision: Any

    execution: Any

    attempted_at: datetime

    account_eligibility: (
        AccountTradingEligibility
        | None
    ) = None

    @property
    def executed(
        self,
    ) -> bool:
        return self.execution is not None


class ProtectiveExitSafetyService:
    """
    Ensures M09 NEW-ENTRY state cannot suppress M06 SELL exits.

    IMPORTANT:
        execute_exit() always delegates to the M06 exit provider.

        AccountTradingEligibility may be supplied for diagnostics
        and audit context, but its ALLOWED/BLOCKED value is never
        used to decide whether the SELL should be attempted.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        exit_execution:
            ProtectiveExitExecutionProvider,
    ) -> None:
        self._broker = broker
        self._account_id = account_id

        self._exit_execution = (
            exit_execution
        )

        self._last_attempt: (
            ProtectiveExitAttempt
            | None
        ) = None

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
    def last_attempt(
        self,
    ) -> ProtectiveExitAttempt | None:
        return self._last_attempt

    def execute_exit(
        self,
        exit_decision: Any,
        *,
        dry_run: bool,
        requested_at: datetime,
        account_eligibility:
            AccountTradingEligibility
            | None = None,
    ) -> ProtectiveExitAttempt:
        """
        Attempt a protective SELL regardless of account-entry
        eligibility.

        Broker/M06 failures are intentionally NOT swallowed.
        They must remain visible to the existing reconciliation
        and failure-supervision layers.
        """

        self._validate_eligibility_identity(
            account_eligibility
        )

        execution = (
            self._exit_execution
            .execute_exit(
                exit_decision,
                dry_run=dry_run,
                requested_at=requested_at,
            )
        )

        attempt = ProtectiveExitAttempt(
            broker=self._broker,
            account_id=self._account_id,
            exit_decision=exit_decision,
            execution=execution,
            attempted_at=requested_at,
            account_eligibility=(
                account_eligibility
            ),
        )

        self._last_attempt = attempt

        return attempt

    def _validate_eligibility_identity(
        self,
        eligibility:
            AccountTradingEligibility
            | None,
    ) -> None:
        """
        Eligibility is diagnostics-only, but if supplied it must
        still refer to the same broker account.
        """

        if eligibility is None:
            return

        if (
            eligibility.broker
            is not self._broker
        ):
            raise ValueError(
                "exit diagnostic eligibility "
                "broker mismatch"
            )

        if (
            eligibility.account_id
            != self._account_id
        ):
            raise ValueError(
                "exit diagnostic eligibility "
                "account mismatch"
            )