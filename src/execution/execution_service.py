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
    BrokerOrderSnapshot,
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
    IdempotencyState,
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


class EntrySubmissionUncertainError(RuntimeError):
    """
    LIVE entry submission crossed the broker boundary but Phoenix
    did not receive a normalized ExecutionResult.

    The exact immutable OrderIntent is retained so application
    orchestration can preserve the pending/reconciliation context
    without reconstructing execution identity.

    M06 idempotency remains SUBMITTED until explicit broker
    reconciliation proves a safe terminal outcome.
    """

    def __init__(
        self,
        *,
        intent: OrderIntent,
        cause: Exception,
    ) -> None:
        self.intent = intent
        self.cause = cause

        super().__init__(
            str(cause)
            or "LIVE entry broker submission outcome is uncertain"
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

    @property
    def broker_submission_attempted(
        self,
    ) -> bool:
        """
        True only when a LIVE broker submission was attempted
        and M06 returned an ExecutionResult.

        This is intentionally different from submitted:

            submitted
                means the broker result reported success.

            broker_submission_attempted
                means Phoenix crossed the LIVE broker boundary,
                regardless of success/status.

        Pre-broker rejection therefore returns False.

        If the broker call itself raises before M06 can return a
        result, callers must inspect the M06 idempotency record.
        SUBMITTED means the broker boundary may have been crossed
        and the M04 signal lock must be retained.
        """

        return (
            self.intent is not None
            and self.intent.execution_mode
            is ExecutionMode.LIVE
            and self.execution_result is not None
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
    def pricing_policy(
        self,
    ) -> OrderPricingPolicy:
        """
        Return the exact pricing policy owned by this M06 service.

        T14 runtime composition uses this read-only boundary so
        account required-cash sizing and the eventual M06 order
        cannot silently use different pricing configuration.
        """

        return self._pricing_policy

    @property
    def quantity_policy(
        self,
    ) -> QuantityPolicy:
        """
        Return the exact quantity policy owned by this M06 service.

        T14 uses the same instance when calculating pre-execution
        lot sizing for M07/M09 gates.
        """

        return self._quantity_policy

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

    @property
    def order_state_machine(
        self,
    ) -> OrderStateMachine:
        """
        Return the exact M06 order lifecycle state machine.

        T14 persistence uses this read-only ownership boundary
        after broker reconciliation so durable state reflects
        the lifecycle already decided by M06 rather than
        independently remapping broker status.
        """

        return self._state_machine

    @property
    def broker_provider(
        self,
    ) -> BrokerExecutionProvider:
        """
        Return the exact broker provider owned by M06.

        T14 must reconcile an entry through the same broker
        boundary that submitted the original order.
        """

        return self._broker_provider

    def refresh_entry_order_status(
        self,
        *,
        intent: OrderIntent,
        execution_result: ExecutionResult,
    ) -> BrokerOrderSnapshot:
        """
        Refresh one already-submitted LIVE entry from broker truth.

        This method does NOT submit another order.

        It:
            - verifies the execution result belongs to the intent,
            - queries the exact M06 broker provider,
            - updates M06 OrderStateMachine when broker truth moves,
            - completes idempotency after a proven full fill,
            - releases submitted idempotency only after a proven
              cancellation.

        UNKNOWN remains RECONCILIATION_REQUIRED and therefore
        non-terminal.
        """

        if (
            execution_result.intent_id
            != intent.intent_id
        ):
            raise ValueError(
                "execution result does not belong "
                "to supplied entry intent"
            )

        broker_reference = (
            execution_result.broker_reference
        )

        if broker_reference is None:
            raise ValueError(
                "entry reconciliation requires "
                "broker reference"
            )

        key = IdempotencyKey.from_signal_id(
            intent.signal.signal_id
        )

        record = self._idempotency_guard.get(
            key
        )

        if record is None:
            raise RuntimeError(
                "entry reconciliation requires "
                "existing idempotency record"
            )

        if (
            record.intent_id
            != intent.intent_id.value
        ):
            raise RuntimeError(
                "idempotency intent does not match "
                "entry intent"
            )

        snapshot = (
            self._broker_provider
            .get_order_status(
                broker_reference
            )
        )

        if (
            snapshot.broker_reference
            != broker_reference
        ):
            raise RuntimeError(
                "broker snapshot reference does not match "
                "entry execution reference"
            )

        if (
            snapshot.quantity
            != intent.quantity
        ):
            raise RuntimeError(
                "broker snapshot quantity does not match "
                "entry intent quantity"
            )

        if (
            snapshot.status
            is BrokerOrderStatus.FILLED
        ):
            if (
                snapshot.filled_quantity
                != intent.quantity
            ):
                raise RuntimeError(
                    "FILLED broker snapshot must prove "
                    "full entry quantity"
                )

            if snapshot.average_price is None:
                raise RuntimeError(
                    "FILLED broker snapshot requires "
                    "average fill price"
                )

        target_state = (
            self._map_broker_status(
                snapshot.status
            )
        )

        current_state = (
            self._state_machine
            .get_state(
                intent.intent_id
            )
        )

        if current_state is not target_state:
            if (
                self._state_machine
                .is_terminal(
                    intent.intent_id
                )
            ):
                raise RuntimeError(
                    "terminal entry order conflicts with "
                    "current broker truth"
                )

            self._state_machine.transition(
                intent.intent_id,
                target_state,
                snapshot.updated_at,
                message=snapshot.message,
            )

        record = self._idempotency_guard.get(
            key
        )

        assert record is not None

        if (
            snapshot.status
            is BrokerOrderStatus.FILLED
            and record.state
            is IdempotencyState.SUBMITTED
        ):
            self._idempotency_guard.mark_completed(
                key=key,
                changed_at=snapshot.updated_at,
            )

        elif (
            snapshot.status
            is BrokerOrderStatus.CANCELLED
            and snapshot.filled_quantity == 0
            and record.state
            is IdempotencyState.SUBMITTED
        ):
            self._idempotency_guard.release_after_reconciliation(
                key=key,
                changed_at=snapshot.updated_at,
            )

        return snapshot

    def cancel_entry_order(
        self,
        *,
        intent: OrderIntent,
        execution_result: ExecutionResult,
    ) -> BrokerOrderSnapshot:
        """
        Request cancellation of one already-submitted LIVE BUY,
        then establish authoritative broker truth.

        The cancellation response itself is never treated as
        final order state.

        Regardless of whether the cancellation request succeeds,
        fails, raises, or reports an ambiguous status, Phoenix
        performs the existing refresh_entry_order_status() path.

        Therefore:

            cancellation request
                ->
            authoritative broker refresh
                ->
            existing M06 lifecycle/idempotency reconciliation

        If both the cancellation request and the authoritative
        refresh fail, the outcome remains uncertain.
        """

        if not isinstance(
            intent,
            OrderIntent,
        ):
            raise TypeError(
                "intent must be OrderIntent"
            )

        if not isinstance(
            execution_result,
            ExecutionResult,
        ):
            raise TypeError(
                "execution_result must be ExecutionResult"
            )

        if (
            execution_result.intent_id
            != intent.intent_id
        ):
            raise ValueError(
                "execution result does not belong "
                "to supplied entry intent"
            )

        broker_reference = (
            execution_result.broker_reference
        )

        if broker_reference is None:
            raise ValueError(
                "entry cancellation requires broker reference"
            )

        cancellation_error: Exception | None = None

        try:
            cancellation = (
                self._broker_provider
                .cancel_order(
                    broker_reference
                )
            )

            if (
                cancellation.broker_reference
                != broker_reference
            ):
                cancellation_error = RuntimeError(
                    "broker cancellation reference does not "
                    "match entry execution reference"
                )

        except Exception as exc:
            # Cancellation transport/result ambiguity does NOT
            # establish order state. Continue to authoritative
            # status reconciliation.
            cancellation_error = exc

        try:
            return self.refresh_entry_order_status(
                intent=intent,
                execution_result=execution_result,
            )

        except Exception as refresh_exc:
            if cancellation_error is not None:
                raise RuntimeError(
                    "entry cancellation could not establish "
                    "authoritative broker truth"
                ) from refresh_exc

            raise


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

        try:
            execution_result = (
                self._broker_provider.submit_order(
                    intent
                )
            )

        except Exception as exc:
            # The broker may have accepted the order before the
            # transport/provider failure became visible locally.
            #
            # Never release the SUBMITTED idempotency reservation.
            # Preserve the exact intent for T14 recovery and make
            # the M06 lifecycle ambiguity explicit.
            self._state_machine.transition(
                intent.intent_id,
                (
                    OrderLifecycleState
                    .RECONCILIATION_REQUIRED
                ),
                requested_at,
                message=(
                    str(exc)
                    or "LIVE broker submission outcome uncertain"
                ),
            )

            raise EntrySubmissionUncertainError(
                intent=intent,
                cause=exc,
            ) from exc

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
                OrderLifecycleState
                .RECONCILIATION_REQUIRED
            ),
        }

        return mapping[status]

    def restore_sequence_floor(
        self,
        floor: int,
    ) -> int:
        """
        Restore the minimum already-consumed BUY intent
        sequence for the trading day.

        Recovery is monotonic and idempotent. It may advance
        the sequence but can never move it backwards.
        """

        if type(floor) is not int:
            raise TypeError(
                "sequence floor must be an integer"
            )

        if floor < 0:
            raise ValueError(
                "sequence floor cannot be negative"
            )

        with self._sequence_lock:
            self._sequence = max(
                self._sequence,
                floor,
            )

            return self._sequence

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
