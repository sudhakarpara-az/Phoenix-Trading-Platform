from datetime import datetime

import pytest

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitIntentState,
    ExitOrderIntent,
    ExitOrderIntentBuilder,
    ExitOrderIntentId,
    ExitOrderSnapshot,
    ExitTransactionType,
)
from src.execution.position_exit_types import (
    ExitOrderType,
    ExitPlan,
    ExitReason,
    FilledPositionId,
)
from src.execution.target_booking_policy import (
    TargetBookingMode,
    TargetBookingPlan,
)
from src.option_selection.option_types import (
    OptionType,
)


NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


def make_target_plan() -> TargetBookingPlan:
    return TargetBookingPlan(
        entry_price=100.0,
        mapped_target_price=129.0,
        target_distance_points=29.0,
        executable_target_price=126.0,
        booking_zone_start=126.0,
        booking_zone_end=129.0,
        mode=TargetBookingMode.NEAR_KS_TARGET,
        tick_size=0.05,
    )


def make_target_exit_plan() -> ExitPlan:
    return ExitPlan(
        position_id=FilledPositionId(
            "POS-M06-T17"
        ),
        security_id="41009",
        symbol="NIFTY50-20260811-24450-CE",
        option_type=OptionType.CALL,
        quantity=65,
        reason=ExitReason.TARGET,
        order_type=ExitOrderType.LIMIT,
        mapped_target_price=129.0,
        target_plan=make_target_plan(),
        exit_price=126.0,
        created_at=NOW,
    )


def make_force_exit_plan() -> ExitPlan:
    return ExitPlan(
        position_id=FilledPositionId(
            "POS-M06-T17"
        ),
        security_id="41009",
        symbol="NIFTY50-20260811-24450-CE",
        option_type=OptionType.CALL,
        quantity=65,
        reason=ExitReason.FORCE_EXIT,
        order_type=ExitOrderType.MARKET,
        mapped_target_price=None,
        target_plan=None,
        exit_price=None,
        created_at=NOW,
    )


def make_exit_intent() -> ExitOrderIntent:
    return ExitOrderIntentBuilder().build(
        intent_id=ExitOrderIntentId(
            "EXIT-M06-T17"
        ),
        exit_plan=make_target_exit_plan(),
        created_at=NOW,
    )


class FakeExitProvider(
    ExitExecutionProvider
):
    def __init__(self) -> None:
        self.submit_count = 0

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent: ExitOrderIntent,
    ) -> ExitExecutionResult:
        self.submit_count += 1

        reference = BrokerOrderReference(
            broker_name="FAKE",
            order_id="EXIT-001",
        )

        return ExitExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=reference,
            submitted_at=NOW,
        )

    def cancel_exit(
        self,
        broker_reference: BrokerOrderReference,
    ) -> ExitCancellationResult:
        return ExitCancellationResult(
            broker_reference=broker_reference,
            success=True,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=NOW,
        )

    def get_exit_status(
        self,
        broker_reference: BrokerOrderReference,
    ) -> ExitOrderSnapshot:
        return ExitOrderSnapshot(
            broker_reference=broker_reference,
            status=BrokerOrderStatus.OPEN,
            quantity=65,
            filled_quantity=0,
            average_price=None,
            updated_at=NOW,
        )


def test_target_exit_plan_builds_sell_limit_intent() -> None:
    intent = ExitOrderIntentBuilder().build(
        intent_id=ExitOrderIntentId(
            "EXIT-001"
        ),
        exit_plan=make_target_exit_plan(),
        created_at=NOW,
    )

    assert (
        intent.transaction_type
        is ExitTransactionType.SELL
    )

    assert (
        intent.order_type
        is ExitOrderType.LIMIT
    )

    assert intent.quantity == 65
    assert intent.price == 126.0

    assert (
        intent.reason
        is ExitReason.TARGET
    )

    assert (
        intent.state
        is ExitIntentState.CREATED
    )


def test_force_exit_builds_market_sell() -> None:
    intent = ExitOrderIntentBuilder().build(
        intent_id=ExitOrderIntentId(
            "EXIT-FORCE"
        ),
        exit_plan=make_force_exit_plan(),
        created_at=NOW,
    )

    assert (
        intent.transaction_type
        is ExitTransactionType.SELL
    )

    assert (
        intent.order_type
        is ExitOrderType.MARKET
    )

    assert intent.price is None

    assert (
        intent.reason
        is ExitReason.FORCE_EXIT
    )


def test_empty_exit_intent_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "exit order intent id cannot be empty"
        ),
    ):
        ExitOrderIntentId(" ")


def test_limit_exit_requires_price() -> None:
    with pytest.raises(
        ValueError,
        match="LIMIT exit requires price",
    ):
        ExitOrderIntent(
            intent_id=ExitOrderIntentId(
                "EXIT-001"
            ),
            position_id=FilledPositionId(
                "POS-001"
            ),
            security_id="41009",
            symbol="NIFTY",
            option_type=OptionType.CALL,
            transaction_type=(
                ExitTransactionType.SELL
            ),
            order_type=ExitOrderType.LIMIT,
            quantity=65,
            price=None,
            reason=ExitReason.TARGET,
            created_at=NOW,
        )


def test_market_exit_cannot_have_price() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "MARKET exit cannot specify price"
        ),
    ):
        ExitOrderIntent(
            intent_id=ExitOrderIntentId(
                "EXIT-001"
            ),
            position_id=FilledPositionId(
                "POS-001"
            ),
            security_id="41009",
            symbol="NIFTY",
            option_type=OptionType.CALL,
            transaction_type=(
                ExitTransactionType.SELL
            ),
            order_type=ExitOrderType.MARKET,
            quantity=65,
            price=126,
            reason=ExitReason.FORCE_EXIT,
            created_at=NOW,
        )


def test_exit_quantity_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "exit quantity must be greater than zero"
        ),
    ):
        ExitOrderIntent(
            intent_id=ExitOrderIntentId(
                "EXIT-001"
            ),
            position_id=FilledPositionId(
                "POS-001"
            ),
            security_id="41009",
            symbol="NIFTY",
            option_type=OptionType.CALL,
            transaction_type=(
                ExitTransactionType.SELL
            ),
            order_type=ExitOrderType.MARKET,
            quantity=0,
            price=None,
            reason=ExitReason.FORCE_EXIT,
            created_at=NOW,
        )


def test_fake_provider_submit_exit() -> None:
    provider = FakeExitProvider()

    result = provider.submit_exit(
        make_exit_intent()
    )

    assert result.success is True

    assert (
        result.status
        is BrokerOrderStatus.OPEN
    )

    assert result.broker_reference is not None

    assert provider.submit_count == 1


def test_successful_exit_requires_reference() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "successful exit execution must contain "
            "broker_reference"
        ),
    ):
        ExitExecutionResult(
            intent_id=ExitOrderIntentId(
                "EXIT-001"
            ),
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=None,
            submitted_at=NOW,
        )


def test_failed_exit_cannot_be_filled() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "failed exit execution cannot have FILLED status"
        ),
    ):
        ExitExecutionResult(
            intent_id=ExitOrderIntentId(
                "EXIT-001"
            ),
            success=False,
            status=BrokerOrderStatus.FILLED,
            broker_reference=None,
            submitted_at=NOW,
        )


def test_exit_snapshot_partial_fill() -> None:
    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="EXIT-001",
    )

    snapshot = ExitOrderSnapshot(
        broker_reference=reference,
        status=(
            BrokerOrderStatus.PARTIALLY_FILLED
        ),
        quantity=65,
        filled_quantity=30,
        average_price=126.0,
        updated_at=NOW,
    )

    assert snapshot.quantity == 65
    assert snapshot.filled_quantity == 30


def test_exit_snapshot_cannot_overfill() -> None:
    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="EXIT-001",
    )

    with pytest.raises(
        ValueError,
        match=(
            "filled_quantity cannot exceed quantity"
        ),
    ):
        ExitOrderSnapshot(
            broker_reference=reference,
            status=BrokerOrderStatus.FILLED,
            quantity=65,
            filled_quantity=66,
            average_price=126,
            updated_at=NOW,
        )


def test_cancel_exit() -> None:
    provider = FakeExitProvider()

    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="EXIT-001",
    )

    result = provider.cancel_exit(
        reference
    )

    assert result.success is True

    assert (
        result.status
        is BrokerOrderStatus.CANCELLED
    )


def test_get_exit_status() -> None:
    provider = FakeExitProvider()

    reference = BrokerOrderReference(
        broker_name="FAKE",
        order_id="EXIT-001",
    )

    snapshot = provider.get_exit_status(
        reference
    )

    assert (
        snapshot.status
        is BrokerOrderStatus.OPEN
    )

    assert snapshot.quantity == 65
    assert snapshot.filled_quantity == 0