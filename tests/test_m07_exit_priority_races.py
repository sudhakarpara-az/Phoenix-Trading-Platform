from datetime import (
    date,
    datetime,
    timedelta,
)

import pytest

from src.execution.execution_types import (
    BrokerOrderReference,
    BrokerOrderStatus,
    ExecutionMode,
    OrderIntentId,
)
from src.execution.exit_execution_provider import (
    ExitCancellationResult,
    ExitExecutionProvider,
    ExitExecutionResult,
    ExitOrderSnapshot,
)
from src.execution.exit_execution_service import (
    ExitExecutionService,
)
from src.execution.exit_plan_builder import (
    ExitPlanBuilder,
)
from src.execution.idempotency_guard import (
    DuplicateOrderGuard,
)
from src.execution.position_exit_types import (
    FilledPosition,
    FilledPositionId,
)
from src.execution.target_booking_policy import (
    TargetBookingPolicy,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.risk.force_exit_coordinator import (
    ForceExitAction,
    ForceExitCoordinator,
)
from src.risk.m06_exit_integration_service import (
    M07ExitIntegrationStatus,
    M07ToM06ExitIntegrationService,
)
from src.risk.option_position_price_monitor import (
    OptionPositionPriceMonitor,
    OptionPriceTick,
)
from src.risk.position_exit_decision_engine import (
    PositionExitDecisionEngine,
    PositionExitDecisionStatus,
)
from src.risk.position_lifecycle_manager import (
    PositionLifecycleManager,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    RiskTriggerType,
    StopLossDefinition,
    TargetDefinition,
)
from src.risk.stop_loss_trigger_monitor import (
    StopLossTriggerMonitor,
)
from src.risk.target_trigger_monitor import (
    TargetTriggerMonitor,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


EXPIRY = date(
    2026,
    8,
    11,
)

NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)

FORCE_TIME = datetime(
    2026,
    8,
    7,
    15,
    15,
)


class CountingExitProvider(
    ExitExecutionProvider
):
    """
    Fake broker provider used only to prove the number of
    submitted SELL orders.
    """

    def __init__(self) -> None:
        self.submit_count = 0
        self.intents = []

    @property
    def broker_name(self) -> str:
        return "FAKE"

    def submit_exit(
        self,
        intent,
    ) -> ExitExecutionResult:
        self.submit_count += 1
        self.intents.append(
            intent
        )

        return ExitExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=(
                BrokerOrderReference(
                    broker_name="FAKE",
                    order_id=(
                        f"EXIT-{self.submit_count}"
                    ),
                )
            ),
            submitted_at=NOW,
        )

    def cancel_exit(
        self,
        broker_reference,
    ) -> ExitCancellationResult:
        raise NotImplementedError

    def get_exit_status(
        self,
        broker_reference,
    ) -> ExitOrderSnapshot:
        raise NotImplementedError


def make_option() -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-24450-CE"
                ),
                security_id="41009",
                option_type=OptionType.CALL,
                strike=24450,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=100,
                bid=99.95,
                ask=100.05,
                volume=1000,
                open_interest=50000,
                received_at=NOW,
            ),
            greeks=OptionGreeks(
                delta=0.64,
                calculated_at=NOW,
            ),
        ),
        selected_at=NOW,
        selection_delta_target=0.64,
    )


def make_filled_position(
    *,
    quantity: int = 65,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T17"
        ),
        signal_id=SignalId(
            "SIG-M07-T17"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T17"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-M07-T17",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=100,
        filled_at=NOW,
    )


def make_position(
    *,
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-T17"
        ),
        position=make_filled_position(
            quantity=quantity
        ),
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
        stop_loss=StopLossDefinition(
            stop_price=85,
            risk_points=15,
        ),
        target=TargetDefinition(
            executable_price=126,
            mapped_target_price=129,
            booking_zone_start=126,
            booking_zone_end=129,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def make_components(
    position: ManagedPosition,
):
    registry = PositionRegistry()

    registry.register(
        position
    )

    price_monitor = (
        OptionPositionPriceMonitor(
            registry=registry
        )
    )

    target_monitor = TargetTriggerMonitor(
        price_monitor=price_monitor,
        max_price_age=timedelta(
            seconds=5
        ),
    )

    stop_monitor = StopLossTriggerMonitor(
        price_monitor=price_monitor,
        max_price_age=timedelta(
            seconds=5
        ),
    )

    decision_engine = (
        PositionExitDecisionEngine()
    )

    lifecycle = PositionLifecycleManager(
        registry=registry
    )

    provider = CountingExitProvider()

    exit_service = ExitExecutionService(
        provider=provider,
        duplicate_guard=DuplicateOrderGuard(),
        allow_live_exit_orders=True,
    )

    integration = (
        M07ToM06ExitIntegrationService(
            registry=registry,
            lifecycle_manager=lifecycle,
            exit_plan_builder=ExitPlanBuilder(
                TargetBookingPolicy()
            ),
            exit_execution_service=exit_service,
        )
    )

    force_exit = ForceExitCoordinator(
        registry=registry
    )

    return (
        registry,
        price_monitor,
        target_monitor,
        stop_monitor,
        decision_engine,
        lifecycle,
        provider,
        integration,
        force_exit,
    )


def push_price(
    monitor: OptionPositionPriceMonitor,
    *,
    ltp: float,
    received_at: datetime,
) -> None:
    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=ltp,
            received_at=received_at,
        )
    )

    assert result.accepted is True


def test_target_only_wins_when_no_other_trigger() -> None:
    position = make_position()

    (
        _,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        _,
        _,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=126,
        received_at=NOW,
    )

    target = target_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    stop = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    decision = decision_engine.decide(
        position=position,
        target_result=target,
        stop_result=stop,
        force_exit=False,
        decided_at=NOW,
    )

    assert decision.exit_required is True

    assert (
        decision.trigger
        is RiskTriggerType.TARGET
    )


def test_stop_only_wins_when_no_other_trigger() -> None:
    position = make_position()

    (
        _,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        _,
        _,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=85,
        received_at=NOW,
    )

    target = target_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    stop = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    decision = decision_engine.decide(
        position=position,
        target_result=target,
        stop_result=stop,
        force_exit=False,
        decided_at=NOW,
    )

    assert decision.exit_required is True

    assert (
        decision.trigger
        is RiskTriggerType.STOP_LOSS
    )


def test_force_exit_has_priority_over_target() -> None:
    position = make_position()

    (
        _,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        _,
        _,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=126,
        received_at=FORCE_TIME,
    )

    target = target_monitor.evaluate(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    stop = stop_monitor.evaluate(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert target.triggered is True
    assert stop.triggered is False

    decision = decision_engine.decide(
        position=position,
        target_result=target,
        stop_result=stop,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    assert (
        decision.trigger
        is RiskTriggerType.FORCE_EXIT
    )


def test_force_exit_has_priority_over_stop() -> None:
    position = make_position()

    (
        _,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        _,
        _,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=85,
        received_at=FORCE_TIME,
    )

    target = target_monitor.evaluate(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    stop = stop_monitor.evaluate(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert stop.triggered is True

    decision = decision_engine.decide(
        position=position,
        target_result=target,
        stop_result=stop,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    assert (
        decision.trigger
        is RiskTriggerType.FORCE_EXIT
    )


def test_stop_has_priority_if_both_trigger_results_are_actionable() -> None:
    """
    Under a coherent single premium tick, an ordinary long
    option cannot simultaneously be <= 85 and >= 126.

    This test therefore checks the engine contract directly
    using trigger results created by separate evaluations.
    """

    position = make_position()

    (
        _,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        _,
        _,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=126,
        received_at=NOW,
    )

    target = target_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    later = NOW + timedelta(
        seconds=1
    )

    push_price(
        prices,
        ltp=85,
        received_at=later,
    )

    stop = stop_monitor.evaluate(
        position=position,
        evaluated_at=later,
    )

    assert target.triggered is True
    assert stop.triggered is True

    decision = decision_engine.decide(
        position=position,
        target_result=target,
        stop_result=stop,
        force_exit=False,
        decided_at=later,
    )

    assert (
        decision.trigger
        is RiskTriggerType.STOP_LOSS
    )


def test_target_submission_creates_only_one_sell() -> None:
    position = make_position()

    (
        registry,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        provider,
        integration,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=126,
        received_at=NOW,
    )

    decision = decision_engine.decide(
        position=position,
        target_result=(
            target_monitor.evaluate(
                position=position,
                evaluated_at=NOW,
            )
        ),
        stop_result=(
            stop_monitor.evaluate(
                position=position,
                evaluated_at=NOW,
            )
        ),
        force_exit=False,
        decided_at=NOW,
    )

    result = integration.execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert (
        result.status
        is M07ExitIntegrationStatus.SUBMITTED
    )

    assert provider.submit_count == 1

    stored = registry.require(
        position.position_id
    )

    assert (
        stored.state
        is ManagedPositionState.EXIT_PENDING
    )


def test_stop_submission_creates_only_one_sell() -> None:
    position = make_position()

    (
        registry,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        provider,
        integration,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=85,
        received_at=NOW,
    )

    decision = decision_engine.decide(
        position=position,
        target_result=(
            target_monitor.evaluate(
                position=position,
                evaluated_at=NOW,
            )
        ),
        stop_result=(
            stop_monitor.evaluate(
                position=position,
                evaluated_at=NOW,
            )
        ),
        force_exit=False,
        decided_at=NOW,
    )

    integration.execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert provider.submit_count == 1

    assert (
        registry.require(
            position.position_id
        ).state
        is ManagedPositionState.EXIT_PENDING
    )


def test_force_exit_submission_creates_only_one_sell() -> None:
    position = make_position()

    (
        _,
        _,
        _,
        _,
        decision_engine,
        _,
        provider,
        integration,
        _,
    ) = make_components(
        position
    )

    decision = decision_engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    integration.execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=FORCE_TIME,
    )

    assert provider.submit_count == 1


def test_price_trigger_just_before_1515_does_not_create_second_force_sell() -> None:
    position = make_position()

    (
        registry,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        provider,
        integration,
        force_coordinator,
    ) = make_components(
        position
    )

    trigger_time = datetime(
        2026,
        8,
        7,
        15,
        14,
        59,
    )

    push_price(
        prices,
        ltp=126,
        received_at=trigger_time,
    )

    decision = decision_engine.decide(
        position=position,
        target_result=(
            target_monitor.evaluate(
                position=position,
                evaluated_at=trigger_time,
            )
        ),
        stop_result=(
            stop_monitor.evaluate(
                position=position,
                evaluated_at=trigger_time,
            )
        ),
        force_exit=False,
        decided_at=trigger_time,
    )

    integration.execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=trigger_time,
    )

    assert provider.submit_count == 1

    stored = registry.require(
        position.position_id
    )

    assert (
        stored.state
        is ManagedPositionState.EXIT_PENDING
    )

    instruction = (
        force_coordinator
        .evaluate_position(
            position=stored,
            evaluated_at=FORCE_TIME,
        )
    )

    assert (
        instruction.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert instruction.force_exit_required is False

    # No second submission occurred.
    assert provider.submit_count == 1


def test_stop_trigger_just_before_1515_does_not_create_second_force_sell() -> None:
    position = make_position()

    (
        registry,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        provider,
        integration,
        force_coordinator,
    ) = make_components(
        position
    )

    trigger_time = datetime(
        2026,
        8,
        7,
        15,
        14,
        59,
    )

    push_price(
        prices,
        ltp=85,
        received_at=trigger_time,
    )

    decision = decision_engine.decide(
        position=position,
        target_result=(
            target_monitor.evaluate(
                position=position,
                evaluated_at=trigger_time,
            )
        ),
        stop_result=(
            stop_monitor.evaluate(
                position=position,
                evaluated_at=trigger_time,
            )
        ),
        force_exit=False,
        decided_at=trigger_time,
    )

    integration.execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=trigger_time,
    )

    assert provider.submit_count == 1

    stored = registry.require(
        position.position_id
    )

    instruction = (
        force_coordinator
        .evaluate_position(
            position=stored,
            evaluated_at=FORCE_TIME,
        )
    )

    assert (
        instruction.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert provider.submit_count == 1


def test_position_becomes_pending_between_decision_and_execution() -> None:
    """
    Race:
        1. T10 creates TARGET decision.
        2. Another exit path marks the position EXIT_PENDING.
        3. Original decision tries to execute.

    Expected:
        second path is blocked before another broker SELL.
    """

    position = make_position()

    (
        registry,
        _,
        _,
        _,
        decision_engine,
        lifecycle,
        provider,
        integration,
        _,
    ) = make_components(
        position
    )

    decision = decision_engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    assert decision.exit_required is True

    # Another thread/path wins the lifecycle race.
    lifecycle.mark_exit_pending(
        position_id=position.position_id,
        trigger=RiskTriggerType.MANUAL,
        changed_at=FORCE_TIME,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "position already has an exit pending"
        ),
    ):
        integration.execute_decision(
            decision=decision,
            execution_mode=ExecutionMode.LIVE,
            requested_at=FORCE_TIME,
        )

    assert provider.submit_count == 0

    assert (
        registry.require(
            position.position_id
        ).state
        is ManagedPositionState.EXIT_PENDING
    )


def test_position_quantity_changes_between_decision_and_execution() -> None:
    """
    Race:
        decision created for 65
        then 30 units are externally reconciled as filled
        before the decision reaches T16

    Expected:
        stale 65-qty exit decision is rejected.
    """

    position = make_position()

    (
        registry,
        _,
        _,
        _,
        decision_engine,
        lifecycle,
        provider,
        integration,
        _,
    ) = make_components(
        position
    )

    decision = decision_engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    assert decision.quantity == 65

    lifecycle.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=120,
        filled_at=FORCE_TIME,
    )

    stored = registry.require(
        position.position_id
    )

    assert stored.open_quantity == 35

    with pytest.raises(
        ValueError,
        match=(
            "exit decision quantity must equal "
            "managed position open quantity"
        ),
    ):
        integration.execute_decision(
            decision=decision,
            execution_mode=ExecutionMode.LIVE,
            requested_at=FORCE_TIME,
        )

    assert provider.submit_count == 0


def test_fresh_decision_after_partial_fill_uses_35_only() -> None:
    position = make_position()

    (
        registry,
        _,
        _,
        _,
        decision_engine,
        lifecycle,
        provider,
        integration,
        _,
    ) = make_components(
        position
    )

    lifecycle.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=30,
        fill_price=120,
        filled_at=FORCE_TIME,
    )

    updated = registry.require(
        position.position_id
    )

    assert (
        updated.state
        is ManagedPositionState.PARTIALLY_EXITED
    )

    decision = decision_engine.decide(
        position=updated,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    assert decision.quantity == 35

    result = integration.execute_decision(
        decision=decision,
        execution_mode=ExecutionMode.LIVE,
        requested_at=FORCE_TIME,
    )

    assert result.submitted is True

    assert provider.submit_count == 1

    assert result.exit_plan is not None
    assert result.exit_plan.quantity == 35


def test_closed_between_decision_and_execution_cannot_submit_sell() -> None:
    position = make_position()

    (
        registry,
        _,
        _,
        _,
        decision_engine,
        lifecycle,
        provider,
        integration,
        _,
    ) = make_components(
        position
    )

    decision = decision_engine.decide(
        position=position,
        target_result=None,
        stop_result=None,
        force_exit=True,
        decided_at=FORCE_TIME,
    )

    lifecycle.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=65,
        fill_price=120,
        filled_at=FORCE_TIME,
    )

    stored = registry.require(
        position.position_id
    )

    assert (
        stored.state
        is ManagedPositionState.CLOSED
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit decision quantity must equal "
            "managed position open quantity"
        ),
    ):
        integration.execute_decision(
            decision=decision,
            execution_mode=ExecutionMode.LIVE,
            requested_at=FORCE_TIME,
        )

    assert provider.submit_count == 0


def test_duplicate_target_monitor_evaluation_does_not_create_two_decisions() -> None:
    position = make_position()

    (
        _,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        _,
        _,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=126,
        received_at=NOW,
    )

    first_target = (
        target_monitor.evaluate(
            position=position,
            evaluated_at=NOW,
        )
    )

    second_target = (
        target_monitor.evaluate(
            position=position,
            evaluated_at=NOW,
        )
    )

    stop = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    first_decision = (
        decision_engine.decide(
            position=position,
            target_result=first_target,
            stop_result=stop,
            force_exit=False,
            decided_at=NOW,
        )
    )

    second_decision = (
        decision_engine.decide(
            position=position,
            target_result=second_target,
            stop_result=stop,
            force_exit=False,
            decided_at=NOW,
        )
    )

    assert first_decision.exit_required is True

    assert (
        first_decision.trigger
        is RiskTriggerType.TARGET
    )

    assert (
        second_decision.status
        is PositionExitDecisionStatus.NO_EXIT
    )


def test_duplicate_stop_monitor_evaluation_does_not_create_two_decisions() -> None:
    position = make_position()

    (
        _,
        prices,
        target_monitor,
        stop_monitor,
        decision_engine,
        _,
        _,
        _,
        _,
    ) = make_components(
        position
    )

    push_price(
        prices,
        ltp=85,
        received_at=NOW,
    )

    target = target_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    first_stop = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    second_stop = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    first_decision = (
        decision_engine.decide(
            position=position,
            target_result=target,
            stop_result=first_stop,
            force_exit=False,
            decided_at=NOW,
        )
    )

    second_decision = (
        decision_engine.decide(
            position=position,
            target_result=target,
            stop_result=second_stop,
            force_exit=False,
            decided_at=NOW,
        )
    )

    assert first_decision.exit_required is True

    assert (
        first_decision.trigger
        is RiskTriggerType.STOP_LOSS
    )

    assert (
        second_decision.status
        is PositionExitDecisionStatus.NO_EXIT
    )


def test_force_coordinator_after_position_closed_has_no_action() -> None:
    position = make_position()

    (
        registry,
        _,
        _,
        _,
        _,
        lifecycle,
        _,
        _,
        coordinator,
    ) = make_components(
        position
    )

    lifecycle.apply_exit_fill(
        position_id=position.position_id,
        fill_quantity=65,
        fill_price=120,
        filled_at=FORCE_TIME,
    )

    closed = registry.require(
        position.position_id
    )

    instruction = coordinator.evaluate_position(
        position=closed,
        evaluated_at=FORCE_TIME,
    )

    assert (
        instruction.action
        is ForceExitAction.NONE
    )

    assert instruction.quantity == 0


def test_partial_exit_pending_at_1515_uses_reconciliation_not_new_sell() -> None:
    position = make_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=ManagedPositionState.EXIT_PENDING,
    )

    (
        _,
        _,
        _,
        _,
        _,
        _,
        provider,
        _,
        coordinator,
    ) = make_components(
        position
    )

    instruction = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        instruction.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert instruction.quantity == 35

    assert provider.submit_count == 0


def test_reconciliation_required_at_1515_never_creates_fresh_sell() -> None:
    position = make_position(
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        )
    )

    (
        _,
        _,
        _,
        _,
        _,
        _,
        provider,
        _,
        coordinator,
    ) = make_components(
        position
    )

    instruction = coordinator.evaluate_position(
        position=position,
        evaluated_at=FORCE_TIME,
    )

    assert (
        instruction.action
        is ForceExitAction
        .RECONCILE_EXISTING_EXIT
    )

    assert instruction.force_exit_required is False

    assert provider.submit_count == 0