"""
Phoenix Execution Service.

Main broker-independent M06 orchestration layer.

Responsibilities:
    - Calculate LIMIT BUY price.
    - Validate quantity.
    - Create OrderIntent.
    - Validate order eligibility.
    - Track order lifecycle.
    - Execute in DRY_RUN mode safely.
    - Route LIVE requests to BrokerExecutionProvider only
      when the explicit live-order gate is enabled.

No Dhan-specific request structure belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from src.execution.broker_execution_provider import (
    BrokerExecutionProvider,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
    ExecutionResult,
    OrderIntent,
    OrderIntentId,
    OrderType,
    TransactionType,
)
from src.execution.order_eligibility_validator import (
    OrderEligibilityContext,
    OrderEligibilityReason,
    OrderEligibilityResult,
    OrderEligibilityValidator,
)
from src.execution.order_pricing_policy import (
    OrderPrice,
    OrderPricingPolicy,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
)
from src.execution.quantity_policy import (
    QuantityPolicy,
)
from src.option_selection.option_types import (
    SelectedOption,
)
from src.signals.signal_types import (
    TradingSignal,
)


@dataclass(frozen=True, slots=True)
class ExecutionServiceResult:
    """
    Complete result of one Phoenix execution request.
    """

    intent: OrderIntent | None

    pricing: OrderPrice | None

    eligibility: OrderEligibilityResult

    execution_result: ExecutionResult | None

    @property
    def accepted(self) -> bool:
        """
        True when order passed Phoenix execution eligibility.
        """

        return self.eligibility.eligible

    @property
    def submitted(self) -> bool:
        """
        True when an execution result exists and succeeded.

        In DRY_RUN this means simulated submission only.
        """

        return (
            self.execution_result is not None
            and self.execution_result.success
        )


class ExecutionService:
    """
    Main Phoenix M06 execution orchestrator.

    LIVE orders are blocked unless allow_live_orders=True.

    Default configuration is intentionally safe:

        allow_live_orders=False
    """

    def __init__(
        self,
        pricing_policy: OrderPricingPolicy,
        quantity_policy: QuantityPolicy,
        eligibility_validator: OrderEligibilityValidator,
        state_machine: OrderStateMachine,
        broker_provider: BrokerExecutionProvider,
        *,
        allow_live_orders: bool = False,
    ) -> None:
        self._pricing_policy = pricing_policy
        self._quantity_policy = quantity_policy
        self._eligibility_validator = eligibility_validator
        self._state_machine = state_machine
        self._broker_provider = broker_provider

        self._allow_live_orders = allow_live_orders

        self._sequence = 0
        self._sequence_lock = RLock()

    @property
    def allow_live_orders(self) -> bool:
        return self._allow_live_orders

    def execute(
        self,
        *,
        signal: TradingSignal,
        selected_option: SelectedOption,
        quantity: int,
        execution_mode: ExecutionMode,
        requested_at: datetime,
        context: OrderEligibilityContext,
    ) -> ExecutionServiceResult:
        """
        Build, validate, register, and process one execution request.
        """

        # --------------------------------------------------
        # Quantity pre-validation
        # --------------------------------------------------

        quantity_result = self._quantity_policy.validate(
            selected_option=selected_option,
            quantity=quantity,
        )

        if not quantity_result.valid:
            eligibility = OrderEligibilityResult(
                eligible=False,
                reason=OrderEligibilityReason.INVALID_QUANTITY,
                message=(
                    quantity_result.message
                    or "execution quantity is invalid"
                ),
            )

            return ExecutionServiceResult(
                intent=None,
                pricing=None,
                eligibility=eligibility,
                execution_result=None,
            )

        # --------------------------------------------------
        # Price calculation
        # --------------------------------------------------

        try:
            pricing = self._pricing_policy.calculate(
                selected_option
            )

        except ValueError as exc:
            eligibility = OrderEligibilityResult(
                eligible=False,
                reason=(
                    OrderEligibilityReason.INVALID_OPTION_LTP
                ),
                message=str(exc),
            )

            return ExecutionServiceResult(
                intent=None,
                pricing=None,
                eligibility=eligibility,
                execution_result=None,
            )

        # --------------------------------------------------
        # Build immutable OrderIntent
        # --------------------------------------------------

        intent = OrderIntent(
            intent_id=self._next_intent_id(
                requested_at
            ),
            signal=signal,
            selected_option=selected_option,
            transaction_type=TransactionType.BUY,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            limit_price=pricing.limit_price,
            execution_mode=execution_mode,
            created_at=requested_at,
        )

        # --------------------------------------------------
        # Register lifecycle
        # --------------------------------------------------

        self._state_machine.register(
            intent
        )

        # --------------------------------------------------
        # Eligibility validation
        # --------------------------------------------------

        eligibility = (
            self._eligibility_validator.validate(
                intent=intent,
                context=context,
            )
        )

        if not eligibility.eligible:
            self._state_machine.transition(
                intent.intent_id,
                OrderLifecycleState.REJECTED,
                requested_at,
                message=(
                    eligibility.message
                    or eligibility.reason.value
                ),
            )

            return ExecutionServiceResult(
                intent=intent,
                pricing=pricing,
                eligibility=eligibility,
                execution_result=None,
            )

        self._state_machine.transition(
            intent.intent_id,
            OrderLifecycleState.VALIDATED,
            requested_at,
        )

        # --------------------------------------------------
        # DRY RUN
        # --------------------------------------------------

        if execution_mode is ExecutionMode.DRY_RUN:
            return self._execute_dry_run(
                intent=intent,
                pricing=pricing,
                eligibility=eligibility,
                requested_at=requested_at,
            )

        # --------------------------------------------------
        # LIVE safety gate
        # --------------------------------------------------

        if not self._allow_live_orders:
            blocked = OrderEligibilityResult(
                eligible=False,
                reason=(
                    OrderEligibilityReason.INVALID_EXECUTION_MODE
                ),
                message=(
                    "LIVE execution is disabled by "
                    "Phoenix safety gate"
                ),
            )

            self._state_machine.transition(
                intent.intent_id,
                OrderLifecycleState.CANCELLED,
                requested_at,
                message=blocked.message,
            )

            return ExecutionServiceResult(
                intent=intent,
                pricing=pricing,
                eligibility=blocked,
                execution_result=None,
            )

        # --------------------------------------------------
        # LIVE broker submission
        # --------------------------------------------------

        self._state_machine.transition(
            intent.intent_id,
            OrderLifecycleState.SUBMITTED,
            requested_at,
        )

        execution_result = (
            self._broker_provider.submit_order(
                intent
            )
        )

        self._apply_execution_result(
            intent=intent,
            result=execution_result,
        )

        return ExecutionServiceResult(
            intent=intent,
            pricing=pricing,
            eligibility=eligibility,
            execution_result=execution_result,
        )

    def _execute_dry_run(
        self,
        *,
        intent: OrderIntent,
        pricing: OrderPrice,
        eligibility: OrderEligibilityResult,
        requested_at: datetime,
    ) -> ExecutionServiceResult:
        """
        Simulate broker submission without making any broker call.

        DRY_RUN deliberately stops at OPEN rather than FILLED.
        It means:
            "Phoenix would submit this order."

        It does not claim the market would actually fill it.
        """

        self._state_machine.transition(
            intent.intent_id,
            OrderLifecycleState.SUBMITTED,
            requested_at,
        )

        self._state_machine.transition(
            intent.intent_id,
            OrderLifecycleState.OPEN,
            requested_at,
            message="DRY_RUN simulated order",
        )

        reference = BrokerOrderReference(
            broker_name="DRY_RUN",
            order_id=(
                f"DRY-{intent.intent_id.value}"
            ),
        )

        result = ExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=reference,
            submitted_at=requested_at,
            message="DRY_RUN - no broker order submitted",
        )

        return ExecutionServiceResult(
            intent=intent,
            pricing=pricing,
            eligibility=eligibility,
            execution_result=result,
        )

    def _apply_execution_result(
        self,
        *,
        intent: OrderIntent,
        result: ExecutionResult,
    ) -> None:
        """
        Translate normalized broker result into Phoenix lifecycle.
        """

        lifecycle_state = self._map_broker_status(
            result.status
        )

        self._state_machine.transition(
            intent.intent_id,
            lifecycle_state,
            result.submitted_at,
            message=result.message,
        )

    @staticmethod
    def _map_broker_status(
        status: BrokerOrderStatus,
    ) -> OrderLifecycleState:
        mapping = {
            BrokerOrderStatus.PENDING: (
                OrderLifecycleState.PENDING
            ),
            BrokerOrderStatus.OPEN: (
                OrderLifecycleState.OPEN
            ),
            BrokerOrderStatus.PARTIALLY_FILLED: (
                OrderLifecycleState.PARTIALLY_FILLED
            ),
            BrokerOrderStatus.FILLED: (
                OrderLifecycleState.FILLED
            ),
            BrokerOrderStatus.REJECTED: (
                OrderLifecycleState.REJECTED
            ),
            BrokerOrderStatus.CANCELLED: (
                OrderLifecycleState.CANCELLED
            ),
            BrokerOrderStatus.UNKNOWN: (
                OrderLifecycleState.FAILED
            ),
        }

        return mapping[status]

    def _next_intent_id(
        self,
        requested_at: datetime,
    ) -> OrderIntentId:
        """
        Generate deterministic process-local order intent ID.
        """

        with self._sequence_lock:
            self._sequence += 1

            sequence = self._sequence

        return OrderIntentId(
            "ORD-"
            f"{requested_at.strftime('%Y%m%d')}-"
            f"{sequence:06d}"
        )