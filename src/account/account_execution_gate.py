"""
Phoenix M09 Account -> M06 Entry Execution Safety Gate.

Responsibilities:
    - refresh current M09 account state before a new BUY
    - calculate account-level trading eligibility
    - block M06 entry submission when account eligibility fails
    - delegate unchanged entry execution to M06 when allowed
    - preserve the latest eligibility decision for audit/debugging

This module does NOT:
    - implement M06 execution
    - place SELL exits
    - calculate M07 risk
    - alter M08 runtime state
    - call Dhan directly

Protective exit semantics remain independent and are tested
separately in M09-T13.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import (
    Any,
    Protocol,
)

from src.account.account_runtime_service import (
    AccountRuntimeRefreshResult,
    AccountRuntimeService,
)
from src.account.account_types import (
    AccountEligibilityReason,
    AccountTradingEligibility,
    BrokerAccountId,
    BrokerType,
)


class EntryExecutionProvider(
    Protocol,
):
    """
    M06-facing entry execution boundary.

    Existing M06 execution implementations/adapters can satisfy
    this contract without being changed.
    """

    def execute_entry(
        self,
        *,
        signal: Any,
        selected_option: Any,
        dry_run: bool,
        requested_at: datetime,
    ) -> Any:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class AccountGatedEntryResult:
    """
    Result of one M09-gated M06 entry attempt.
    """

    eligibility: AccountTradingEligibility

    execution: Any | None

    evaluated_at: datetime

    @property
    def executed(
        self,
    ) -> bool:
        return self.execution is not None

    @property
    def blocked(
        self,
    ) -> bool:
        return not self.executed


class AccountEntryBlockedError(
    RuntimeError
):
    """
    M09 account state does not permit a new entry.
    """

    def __init__(
        self,
        *,
        eligibility:
            AccountTradingEligibility,
    ) -> None:
        self.eligibility = eligibility

        super().__init__(
            "account entry blocked: "
            f"{eligibility.reason.value}"
        )


class AccountExecutionSafetyGate:
    """
    Account-level safety boundary in front of M06 BUY execution.

    Every new entry receives a current M09 refresh using the cash
    requirement calculated for that order.

    If M09 denies the entry, the M06 execution provider is never
    called.
    """

    def __init__(
        self,
        *,
        broker: BrokerType,
        account_id: BrokerAccountId,
        account_runtime:
            AccountRuntimeService,
        entry_execution:
            EntryExecutionProvider,
    ) -> None:
        self._broker = broker

        self._account_id = account_id

        self._account_runtime = (
            account_runtime
        )

        self._entry_execution = (
            entry_execution
        )

        self._last_result: (
            AccountGatedEntryResult
            | None
        ) = None

        self._validate_identity()

    # ========================================================
    # Identity / state
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

    @property
    def entry_execution(
        self,
    ) -> EntryExecutionProvider:
        """
        Return the exact M06-facing entry execution provider
        owned by this M09 gate.

        T14 uses this read-only boundary to prove that the
        adapter used for pre-gate sizing is the same adapter
        M09 delegates to after account approval.
        """

        return self._entry_execution

    @property
    def last_result(
        self,
    ) -> AccountGatedEntryResult | None:
        return self._last_result

    @property
    def last_eligibility(
        self,
    ) -> AccountTradingEligibility | None:
        if self._last_result is None:
            return None

        return (
            self._last_result
            .eligibility
        )

    # ========================================================
    # Entry gate
    # ========================================================

    def execute_entry(
        self,
        *,
        signal: Any,
        selected_option: Any,
        required_cash: Decimal,
        dry_run: bool,
        requested_at: datetime,
    ) -> AccountGatedEntryResult:
        """
        Refresh M09 account state and conditionally invoke M06.

        IMPORTANT:
            M06 is called only after M09 returns ALLOWED.
        """

        if required_cash < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        refresh_result = (
            self._account_runtime
            .refresh(
                required_cash=(
                    required_cash
                ),
                refreshed_at=(
                    requested_at
                ),
            )
        )

        eligibility = (
            refresh_result.eligibility
        )

        if not eligibility.allowed:
            result = AccountGatedEntryResult(
                eligibility=eligibility,
                execution=None,
                evaluated_at=requested_at,
            )

            self._last_result = result

            raise AccountEntryBlockedError(
                eligibility=eligibility
            )

        execution = (
            self._entry_execution
            .execute_entry(
                signal=signal,
                selected_option=(
                    selected_option
                ),
                dry_run=dry_run,
                requested_at=(
                    requested_at
                ),
            )
        )

        result = AccountGatedEntryResult(
            eligibility=eligibility,
            execution=execution,
            evaluated_at=requested_at,
        )

        self._last_result = result

        return result

    # ========================================================
    # Non-throwing evaluation helper
    # ========================================================

    def evaluate_only(
        self,
        *,
        required_cash: Decimal,
        evaluated_at: datetime,
    ) -> AccountRuntimeRefreshResult:
        """
        Evaluate account readiness without invoking M06.

        Useful for startup/monitoring and tests.
        """

        if required_cash < Decimal("0"):
            raise ValueError(
                "required cash cannot be negative"
            )

        return (
            self._account_runtime
            .refresh(
                required_cash=(
                    required_cash
                ),
                refreshed_at=(
                    evaluated_at
                ),
            )
        )

    # ========================================================
    # Validation
    # ========================================================

    def _validate_identity(
        self,
    ) -> None:
        if (
            self._account_runtime.broker
            is not self._broker
        ):
            raise ValueError(
                "account execution gate "
                "broker mismatch"
            )

        if (
            self._account_runtime.account_id
            != self._account_id
        ):
            raise ValueError(
                "account execution gate "
                "account mismatch"
            )