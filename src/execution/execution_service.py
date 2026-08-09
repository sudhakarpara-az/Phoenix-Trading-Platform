"""
Phoenix Execution Service.

Main broker-independent M06 orchestration layer.

Responsibilities:
    - Prevent duplicate execution of one TradingSignal.
    - Calculate LIMIT BUY price.
    - Validate quantity.
    - Create immutable OrderIntent.
    - Validate execution eligibility.
    - Track order lifecycle.
    - Route DRY_RUN requests to DryRunExecutor.
    - Route LIVE requests to BrokerExecutionProvider only
      after explicit safety-gate enablement.

No Dhan-specific request structures belong here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from src.execution.broker_execution_provider import (
    BrokerExecutionProvider,
)
from src.execution.dry_run_executor import (
    DryRunExecutor,
)
from src.execution.execution_types import (
    BrokerOrderStatus,
    ExecutionMode,
    ExecutionResult,
    OrderIntent,
    OrderIntentId,
    OrderType,
    TransactionType,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
    IdempotencyKey,
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
        return self.eligibility.eligible

    @property
    def submitted(self) -> bool:
        return (
            self.execution_result is not None
            and self.execution_result.success
        )


class ExecutionService:
    """
    Main Phoenix execution orchestrator.

    LIVE execution is blocked by default.
    """

    def __init__(
        self,
        pricing_policy: OrderPricingPolicy,
        quantity_policy: QuantityPolicy,
        eligibility_validator: OrderEligibilityValidator,
        state_machine: OrderStateMachine,
        broker_provider: BrokerExecutionProvider,
        *,
        idempotency_guard: DuplicateOrderGuard | None = None,
        dry_run_executor: DryRunExecutor | None = None,
        allow_live_orders: bool = False,
    ) -> None:
        self._pricing_policy = pricing_policy
        self._quantity_policy = quantity_policy
        self._eligibility_validator = eligibility_validator
        self._state_machine = state_machine
        self._broker_provider = broker_provider

        self._idempotency_guard = (
            idempotency_guard
            or DuplicateOrderGuard()
        )

        self._dry_run_executor = (
            dry_run_executor
            or DryRunExecutor()
        )

        self._allow_live_orders = (
            allow_live_orders
        )

        self._sequence = 0
        self._sequence_lock = RLock()

    @property
    def allow_live_orders(self) -> bool:
        return self._allow_live_orders

    @property
    def dry_run_executor(
        self,
    ) -> DryRunExecutor:
        return self._dry_run_executor

    @property
    def idempotency_guard(
        self,
    ) -> DuplicateOrderGuard:
        return self._idempotency_guard

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
        Process one Phoenix execution request.
        """

        # --------------------------------------------------
        # Idempotency reservation
        # --------------------------------------------------

        key = IdempotencyKey.from_signal_id(
            signal.signal_id
        )

        reservation = (
            self._idempotency_guard.reserve(
                key=key,
                created_at=requested_at,
            )
        )

        if not reservation.acquired:
            return ExecutionServiceResult(
                intent=None,
                pricing=None,
                eligibility=OrderEligibilityResult(
                    eligible=False,
                    reason=(
                        OrderEligibilityReason
                        .DUPLICATE_ORDER
                    ),
                    message=(
                        "execution already exists "
                        "for this signal"
                    ),
                ),
                execution_result=None,
            )

        # --------------------------------------------------
        # Signal / selected-option contract validation
        # --------------------------------------------------

        if (
            signal.direction.value
            != selected_option.option_type.value
        ):
            self._idempotency_guard.release(
                key=key,
                changed_at=requested_at,
            )

            return ExecutionServiceResult(
                intent=None,
                pricing=None,
                eligibility=OrderEligibilityResult(
                    eligible=False,
                    reason=(
                        OrderEligibilityReason
                        .SIDE_MISMATCH
                    ),
                    message=(
                        "signal direction and selected "
                        "option type do not match"
                    ),
                ),
                execution_result=None,
            )

        if (
            signal.instrument_security_id
            != selected_option.security_id
            or signal.instrument_symbol
            != selected_option.symbol
        ):
            self._idempotency_guard.release(
                key=key,
                changed_at=requested_at,
            )

            return ExecutionServiceResult(
                intent=None,
                pricing=None,
                eligibility=OrderEligibilityResult(
                    eligible=False,
                    reason=(
                        OrderEligibilityReason
                        .CONTRACT_MISMATCH
                    ),
                    message=(
                        "signal contract identity does not "
                        "match selected option contract"
                    ),
                ),
                execution_result=None,
            )

        # --------------------------------------------------
        # Quantity pre-validation
        # --------------------------------------------------

        quantity_result = (
            self._quantity_policy.validate(
                selected_option=selected_option,
                quantity=quantity,
            )
        )

        if not quantity_result.valid:
            self._idempotency_guard.release(
                key=key,
                changed_at=requested_at,
            )

            return ExecutionServiceResult(
                intent=None,
                pricing=None,
                eligibility=OrderEligibilityResult(
                    eligible=False,
                    reason=(
                        OrderEligibilityReason
                        .INVALID_QUANTITY
                    ),
                    message=(
                        quantity_result.message
                        or "execution quantity is invalid"
                    ),
                ),
                execution_result=None,
            )

        # --------------------------------------------------
        # Pricing
        # --------------------------------------------------

        try:
            pricing = (
                self._pricing_policy.calculate(
                    selected_option
                )
            )

        except ValueError as exc:
            self._idempotency_guard.release(
                key=key,
                changed_at=requested_at,
            )

            return ExecutionServiceResult(
                intent=None,
                pricing=None,
                eligibility=OrderEligibilityResult(
                    eligible=False,
                    reason=(
                        OrderEligibilityReason
                        .INVALID_OPTION_LTP
                    ),
                    message=str(exc),
                ),
                execution_result=None,
            )

        # --------------------------------------------------
        # Build immutable intent
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

        self._idempotency_guard.attach_intent(
            key=key,
            intent=intent,
            changed_at=requested_at,
        )

        self._state_machine.register(
            intent
        )

        # --------------------------------------------------
        # Eligibility
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

            # No broker submission occurred.
            # Safe to release signal reservation.
            self._idempotency_guard.release(
                key=key,
                changed_at=requested_at,
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
                key=key,
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
                    OrderEligibilityReason
                    .LIVE_EXECUTION_DISABLED
                ),
                message=(
                    "LIVE execution is disabled "
                    "by Phoenix safety gate"
                ),
            )

            self._state_machine.transition(
                intent.intent_id,
                OrderLifecycleState.CANCELLED,
                requested_at,
                message=blocked.message,
            )

            # No broker call occurred, therefore reservation
            # may safely be released.
            self._idempotency_guard.release(
                key=key,
                changed_at=requested_at,
            )

            return ExecutionServiceResult(
                intent=intent,
                pricing=pricing,
                eligibility=blocked,
                execution_result=None,
            )

        # --------------------------------------------------
        # LIVE broker submission
        #
        # Critical safety ordering:
        #
        # mark SUBMITTED BEFORE calling broker.
        #
        # If the network dies after broker acceptance but
        # before Phoenix receives the response, the key remains
        # SUBMITTED and cannot generate another BUY.
        # --------------------------------------------------

        self._state_machine.transition(
            intent.intent_id,
            OrderLifecycleState.SUBMITTED,
            requested_at,
        )

        self._idempotency_guard.mark_submitted(
            key=key,
            changed_at=requested_at,
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

        # Once broker submission was attempted, never release
        # the idempotency key automatically.
        #
        # A broker timeout may mean the order actually exists.

        if (
            execution_result.status
            is BrokerOrderStatus.FILLED
        ):
            self._idempotency_guard.mark_completed(
                key=key,
                changed_at=(
                    execution_result.submitted_at
                ),
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
        key: IdempotencyKey,
        intent: OrderIntent,
        pricing: OrderPrice,
        eligibility: OrderEligibilityResult,
        requested_at: datetime,
    ) -> ExecutionServiceResult:
        """
        Execute through the explicit dry-run simulator.
        """

        self._state_machine.transition(
            intent.intent_id,
            OrderLifecycleState.SUBMITTED,
            requested_at,
        )

        self._idempotency_guard.mark_submitted(
            key=key,
            changed_at=requested_at,
        )

        result = self._dry_run_executor.execute(
            intent=intent,
            executed_at=requested_at,
        )

        self._apply_execution_result(
            intent=intent,
            result=result,
        )

        # Dry run represents successful processing of this
        # logical signal. Mark it completed so replaying the
        # same signal cannot create another simulated order.
        self._idempotency_guard.mark_completed(
            key=key,
            changed_at=requested_at,
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
        lifecycle_state = (
            self._map_broker_status(
                result.status
            )
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
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence

        return OrderIntentId(
            "ORD-"
            f"{requested_at.strftime('%Y%m%d')}-"
            f"{sequence:06d}"
        )