"""
Phoenix M06 runtime entry adapter.

Formal T14 integration boundary:

    EntryOrderSizingPolicy
        +
    M06 ExecutionService
        ->
    M09-compatible execute_entry() port

Critical invariant:

    The pre-account-gate required_cash calculation and the actual
    M06 order submission MUST use the same pricing and quantity
    policy instances.

This prevents a configuration mismatch where M09 approves cash
for one LIMIT price/quantity while M06 submits another.

This adapter does not:
    - perform M10 scheduler gating
    - perform M04 signal eligibility
    - perform M07 exposure/daily-risk checks
    - perform M09 account eligibility itself
    - build filled positions
    - submit exits
"""

from __future__ import annotations

from datetime import datetime

from src.execution.entry_order_sizing_policy import (
    EntryOrderSizing,
    EntryOrderSizingPolicy,
)
from src.execution.execution_service import (
    ExecutionService,
    ExecutionServiceResult,
)
from src.execution.execution_types import (
    ExecutionMode,
)
from src.execution.order_eligibility_validator import (
    OrderEligibilityContext,
)
from src.option_selection.option_types import (
    SelectedOption,
)
from src.signals.signal_types import (
    TradingSignal,
)


class M06EntryRuntimeAdapter:
    """
    Adapts M06 ExecutionService to the M09 entry-execution port.

    The adapter owns one preferred-lot configuration.

    Sizing is calculated before M09 eligibility so required cash
    is known. When M09 later delegates execute_entry(), the same
    sizing policy is recalculated deterministically from the same
    M06 policy instances.
    """

    def __init__(
        self,
        *,
        execution_service: ExecutionService,
        preferred_lots: int = 1,
    ) -> None:
        if (
            isinstance(preferred_lots, bool)
            or not isinstance(
                preferred_lots,
                int,
            )
        ):
            raise TypeError(
                "preferred_lots must be an integer"
            )

        if preferred_lots <= 0:
            raise ValueError(
                "preferred_lots must be greater than zero"
            )

        self._execution_service = (
            execution_service
        )

        self._preferred_lots = (
            preferred_lots
        )

        # ----------------------------------------------------
        # Critical ownership rule:
        #
        # Do not instantiate independent OrderPricingPolicy or
        # QuantityPolicy objects here.
        #
        # M09 cash approval and M06 submission must share the
        # exact policies owned by ExecutionService.
        # ----------------------------------------------------
        self._sizing_policy = (
            EntryOrderSizingPolicy(
                quantity_policy=(
                    execution_service
                    .quantity_policy
                ),
                pricing_policy=(
                    execution_service
                    .pricing_policy
                ),
            )
        )

    @property
    def execution_service(
        self,
    ) -> ExecutionService:
        return self._execution_service

    @property
    def sizing_policy(
        self,
    ) -> EntryOrderSizingPolicy:
        return self._sizing_policy

    @property
    def preferred_lots(
        self,
    ) -> int:
        return self._preferred_lots

    def calculate_sizing(
        self,
        *,
        selected_option: SelectedOption,
    ) -> EntryOrderSizing:
        """
        Calculate quantity, LIMIT price and required cash.

        This method is intended to be called by the T14 entry
        coordinator before invoking M09 AccountExecutionSafetyGate.
        """

        return self._sizing_policy.calculate(
            selected_option=selected_option,
            preferred_lots=self._preferred_lots,
        )

    def execute_entry(
        self,
        *,
        signal: TradingSignal,
        selected_option: SelectedOption,
        dry_run: bool,
        requested_at: datetime,
    ) -> ExecutionServiceResult:
        """
        Execute one already-gated entry through M06.

        This signature intentionally satisfies the existing M09
        EntryExecutionProvider protocol.
        """

        if type(dry_run) is not bool:
            raise TypeError(
                "dry_run must be bool"
            )

        if type(requested_at) is not datetime:
            raise TypeError(
                "requested_at must be a datetime"
            )

        sizing = self.calculate_sizing(
            selected_option=selected_option
        )

        execution_mode = (
            ExecutionMode.DRY_RUN
            if dry_run
            else ExecutionMode.LIVE
        )

        result = (
            self._execution_service
            .execute(
                signal=signal,
                selected_option=selected_option,
                quantity=(
                    sizing.requested_quantity
                ),
                execution_mode=execution_mode,
                requested_at=requested_at,
                context=OrderEligibilityContext(),
            )
        )

        # ----------------------------------------------------
        # Defensive deterministic-contract validation.
        #
        # These checks occur against the M06 result to prove that
        # the sizing used for upstream M07/M09 gates corresponds
        # to the order M06 actually constructed.
        #
        # Both calculations use identical policy instances, so a
        # mismatch indicates a programming/integration fault.
        # ----------------------------------------------------

        if result.intent is not None:
            if (
                result.intent.quantity
                != sizing.requested_quantity
            ):
                raise RuntimeError(
                    "M06 order quantity differs from "
                    "pre-gated entry sizing"
                )

            if (
                result.intent.limit_price
                != sizing.pricing.limit_price
            ):
                raise RuntimeError(
                    "M06 LIMIT price differs from "
                    "pre-gated entry sizing"
                )

        if (
            result.pricing is not None
            and result.pricing.limit_price
            != sizing.pricing.limit_price
        ):
            raise RuntimeError(
                "M06 pricing result differs from "
                "pre-gated entry sizing"
            )

        return result


__all__ = [
    "M06EntryRuntimeAdapter",
]
