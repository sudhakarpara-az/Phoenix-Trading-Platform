from __future__ import annotations

from datetime import timedelta

from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
)
from src.execution.execution_service import (
    ExecutionService,
)
from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionResult,
    OrderIntent,
)
from src.execution.order_eligibility_validator import (
    OrderEligibilityValidator,
)
from src.execution.order_pricing_policy import (
    OrderPricingPolicy,
)
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
)
from src.execution.quantity_policy import (
    QuantityPolicy,
)

from tests.test_m06_entry_status_reconciliation import (
    NOW,
    execute_open_entry,
)


class CancellationBroker(
    BrokerExecutionProvider,
):
    """
    Focused cancellation-capable implementation of the exact
    M06 broker execution boundary.
    """

    def __init__(
        self,
    ) -> None:
        self.current_status = (
            BrokerOrderStatus.OPEN
        )

        self.filled_quantity = 0

        self.average_price: (
            float | None
        ) = None

        self.reference = (
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-CANCEL-001",
            )
        )

        self.quantity: int | None = None

        self.status_calls = 0
        self.cancel_calls = 0

        self.cancel_reported_status = (
            BrokerOrderStatus.CANCELLED
        )

        self.after_cancel_status = (
            BrokerOrderStatus.CANCELLED
        )

        self.cancel_exception: (
            Exception | None
        ) = None

    @property
    def broker_name(
        self,
    ) -> str:
        return "DHAN"

    def submit_order(
        self,
        intent: OrderIntent,
    ) -> ExecutionResult:
        self.quantity = (
            intent.quantity
        )

        return ExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=self.reference,
            submitted_at=NOW,
        )

    def cancel_order(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> BrokerCancellationResult:
        self.cancel_calls += 1

        if (
            broker_reference
            != self.reference
        ):
            raise AssertionError(
                "unexpected cancellation broker reference"
            )

        if self.cancel_exception is not None:
            raise self.cancel_exception

        self.current_status = (
            self.after_cancel_status
        )

        return BrokerCancellationResult(
            broker_reference=(
                broker_reference
            ),
            success=(
                self.cancel_reported_status
                is BrokerOrderStatus.CANCELLED
            ),
            status=(
                self.cancel_reported_status
            ),
            cancelled_at=(
                NOW
                + timedelta(seconds=1)
            ),
        )

    def get_order_status(
        self,
        broker_reference:
            BrokerOrderReference,
    ) -> BrokerOrderSnapshot:
        self.status_calls += 1

        if (
            broker_reference
            != self.reference
        ):
            raise AssertionError(
                "unexpected status broker reference"
            )

        if self.quantity is None:
            raise AssertionError(
                "order must be submitted before status refresh"
            )

        return BrokerOrderSnapshot(
            broker_reference=(
                self.reference
            ),
            status=self.current_status,
            quantity=self.quantity,
            filled_quantity=(
                self.filled_quantity
            ),
            average_price=(
                self.average_price
            ),
            updated_at=(
                NOW
                + timedelta(seconds=2)
            ),
        )


def make_cancel_service():
    broker = CancellationBroker()

    state_machine = (
        OrderStateMachine()
    )

    service = ExecutionService(
        pricing_policy=(
            OrderPricingPolicy()
        ),
        quantity_policy=(
            QuantityPolicy()
        ),
        eligibility_validator=(
            OrderEligibilityValidator()
        ),
        state_machine=state_machine,
        broker_provider=broker,
        allow_live_orders=True,
    )

    return (
        service,
        broker,
        state_machine,
    )


def test_confirmed_cancel_requires_post_cancel_refresh():
    (
        service,
        broker,
        state_machine,
    ) = make_cancel_service()

    _, result = execute_open_entry(
        service
    )

    assert result.intent is not None
    assert result.execution_result is not None

    snapshot = service.cancel_entry_order(
        intent=result.intent,
        execution_result=(
            result.execution_result
        ),
    )

    assert broker.cancel_calls == 1
    assert broker.status_calls == 1

    assert (
        snapshot.status
        is BrokerOrderStatus.CANCELLED
    )

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.CANCELLED
    )


def test_cancel_response_unknown_but_refresh_cancelled_wins():
    (
        service,
        broker,
        _,
    ) = make_cancel_service()

    _, result = execute_open_entry(
        service
    )

    assert result.intent is not None
    assert result.execution_result is not None

    broker.cancel_reported_status = (
        BrokerOrderStatus.UNKNOWN
    )

    broker.after_cancel_status = (
        BrokerOrderStatus.CANCELLED
    )

    snapshot = service.cancel_entry_order(
        intent=result.intent,
        execution_result=(
            result.execution_result
        ),
    )

    assert broker.cancel_calls == 1
    assert broker.status_calls == 1

    assert (
        snapshot.status
        is BrokerOrderStatus.CANCELLED
    )


def test_cancel_transport_error_but_refresh_open_remains_open():
    (
        service,
        broker,
        state_machine,
    ) = make_cancel_service()

    _, result = execute_open_entry(
        service
    )

    assert result.intent is not None
    assert result.execution_result is not None

    broker.cancel_exception = (
        RuntimeError(
            "cancel transport failed"
        )
    )

    broker.current_status = (
        BrokerOrderStatus.OPEN
    )

    snapshot = service.cancel_entry_order(
        intent=result.intent,
        execution_result=(
            result.execution_result
        ),
    )

    assert broker.cancel_calls == 1
    assert broker.status_calls == 1

    assert (
        snapshot.status
        is BrokerOrderStatus.OPEN
    )

    assert (
        state_machine.get_state(
            result.intent.intent_id
        )
        is OrderLifecycleState.OPEN
    )
