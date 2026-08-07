from datetime import datetime

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderSnapshot,
)
from src.execution.exit_execution_service import (
    ExitExecutionDecision,
    ExitExecutionService,
)
from src.execution.idempotency_guard import (
    IdempotencyKey,
    IdempotencyState,
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


class CountingExitProvider(
    ExitExecutionProvider
):
    def __init__(
        self,
        *,
        status: BrokerOrderStatus = (
            BrokerOrderStatus.OPEN
        ),
    ) -> None:
        self.submit_count = 0
        self.status = status
        self.last_intent = None

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent,
    ) -> ExitExecutionResult:
        self.submit_count += 1
        self.last_intent = intent

        return ExitExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=self.status,
            broker_reference=(
                BrokerOrderReference(
                    broker_name="FAKE",
                    order_id="EXIT-001",
                )
            ),
            submitted_at=NOW,
        )

    def cancel_exit(
        self,
        broker_reference,
    ) -> ExitCancellationResult:
        return ExitCancellationResult(
            broker_reference=broker_reference,
            success=True,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=NOW,
        )

    def get_exit_status(
        self,
        broker_reference,
    ) -> ExitOrderSnapshot:
        return ExitOrderSnapshot(
            broker_reference=broker_reference,
            status=self.status,
            quantity=65,
            filled_quantity=0,
            average_price=None,
            updated_at=NOW,
        )


def make_target_plan() -> TargetBookingPlan:
    return TargetBookingPlan(
        entry_price=100,
        mapped_target_price=129,
        target_distance_points=29,
        executable_target_price=126,
        booking_zone_start=126,
        booking_zone_end=129,
        mode=(
            TargetBookingMode.NEAR_KS_TARGET
        ),
        tick_size=0.05,
    )


def make_exit_plan(
    *,
    position_id: str = "POS-T19-001",
) -> ExitPlan:
    return ExitPlan(
        position_id=FilledPositionId(
            position_id
        ),
        security_id="41009",
        symbol=(
            "NIFTY50-20260811-24450-CE"
        ),
        option_type=OptionType.CALL,
        quantity=65,
        reason=ExitReason.TARGET,
        order_type=ExitOrderType.LIMIT,
        mapped_target_price=129,
        target_plan=make_target_plan(),
        exit_price=126,
        created_at=NOW,
    )


def make_service(
    *,
    allow_live_exit_orders: bool = False,
    status: BrokerOrderStatus = (
        BrokerOrderStatus.OPEN
    ),
):
    provider = CountingExitProvider(
        status=status
    )

    service = ExitExecutionService(
        provider=provider,
        allow_live_exit_orders=(
            allow_live_exit_orders
        ),
    )

    return service, provider


def test_dry_run_is_accepted() -> None:
    service, provider = make_service()

    result = service.execute(
        exit_plan=make_exit_plan(),
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    assert result.accepted is True
    assert result.submitted is True

    assert (
        result.decision
        is ExitExecutionDecision.ACCEPTED
    )

    assert provider.submit_count == 0


def test_dry_run_creates_sell_intent() -> None:
    service, _ = make_service()

    result = service.execute(
        exit_plan=make_exit_plan(),
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    assert result.intent is not None

    assert (
        result.intent.transaction_type.value
        == "SELL"
    )

    assert (
        result.intent.order_type
        is ExitOrderType.LIMIT
    )

    assert result.intent.price == 126


def test_dry_run_reference_is_marked_dry_run() -> None:
    service, _ = make_service()

    result = service.execute(
        exit_plan=make_exit_plan(),
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    assert result.execution_result is not None

    reference = (
        result.execution_result
        .broker_reference
    )

    assert reference is not None

    assert (
        reference.broker_name
        == "DRY_RUN"
    )


def test_same_position_cannot_exit_twice() -> None:
    service, provider = make_service()

    plan = make_exit_plan(
        position_id="POS-SAME"
    )

    first = service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    second = service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    assert first.accepted is True

    assert second.accepted is False

    assert (
        second.decision
        is ExitExecutionDecision.DUPLICATE_EXIT
    )

    assert second.intent is None

    assert provider.submit_count == 0


def test_different_positions_can_exit() -> None:
    service, _ = make_service()

    first = service.execute(
        exit_plan=make_exit_plan(
            position_id="POS-001"
        ),
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    second = service.execute(
        exit_plan=make_exit_plan(
            position_id="POS-002"
        ),
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    assert first.accepted is True
    assert second.accepted is True


def test_dry_run_marks_position_exit_completed() -> None:
    service, _ = make_service()

    plan = make_exit_plan()

    service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{plan.position_id.value}"
    )

    record = (
        service.duplicate_guard.get(
            key
        )
    )

    assert record is not None

    assert (
        record.state
        is IdempotencyState.COMPLETED
    )


def test_live_exit_blocked_by_default() -> None:
    service, provider = make_service(
        allow_live_exit_orders=False
    )

    result = service.execute(
        exit_plan=make_exit_plan(),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.accepted is False

    assert (
        result.decision
        is ExitExecutionDecision
        .LIVE_EXIT_DISABLED
    )

    assert provider.submit_count == 0


def test_blocked_live_exit_releases_guard() -> None:
    service, _ = make_service(
        allow_live_exit_orders=False
    )

    plan = make_exit_plan()

    service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{plan.position_id.value}"
    )

    assert (
        service.duplicate_guard
        .is_blocked(key)
        is False
    )


def test_live_enabled_calls_provider() -> None:
    service, provider = make_service(
        allow_live_exit_orders=True
    )

    result = service.execute(
        exit_plan=make_exit_plan(),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.accepted is True
    assert result.submitted is True

    assert provider.submit_count == 1


def test_live_duplicate_calls_provider_once() -> None:
    service, provider = make_service(
        allow_live_exit_orders=True
    )

    plan = make_exit_plan()

    first = service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    second = service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert first.accepted is True
    assert second.accepted is False

    assert provider.submit_count == 1


def test_filled_live_exit_completes_guard() -> None:
    service, _ = make_service(
        allow_live_exit_orders=True,
        status=BrokerOrderStatus.FILLED,
    )

    plan = make_exit_plan()

    service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{plan.position_id.value}"
    )

    record = (
        service.duplicate_guard.get(
            key
        )
    )

    assert record is not None

    assert (
        record.state
        is IdempotencyState.COMPLETED
    )


def test_open_live_exit_remains_submitted() -> None:
    service, _ = make_service(
        allow_live_exit_orders=True,
        status=BrokerOrderStatus.OPEN,
    )

    plan = make_exit_plan()

    service.execute(
        exit_plan=plan,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    key = IdempotencyKey(
        "EXIT_POSITION:"
        f"{plan.position_id.value}"
    )

    record = (
        service.duplicate_guard.get(
            key
        )
    )

    assert record is not None

    assert (
        record.state
        is IdempotencyState.SUBMITTED
    )


def test_exit_intent_ids_are_unique() -> None:
    service, _ = make_service()

    first = service.execute(
        exit_plan=make_exit_plan(
            position_id="POS-001"
        ),
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    second = service.execute(
        exit_plan=make_exit_plan(
            position_id="POS-002"
        ),
        execution_mode=ExecutionMode.DRY_RUN,
        requested_at=NOW,
    )

    assert first.intent is not None
    assert second.intent is not None

    assert (
        first.intent.intent_id.value
        != second.intent.intent_id.value
    )