from datetime import (
    date,
    datetime,
)

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
    ExitOrderType,
    ExitReason,
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
from src.risk.m06_exit_integration_service import (
    M07ExitIntegrationStatus,
    M07ToM06ExitIntegrationService,
)
from src.risk.position_exit_decision_engine import (
    PositionExitDecision,
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


class FakeExitProvider(
    ExitExecutionProvider
):
    def __init__(
        self,
        *,
        accepted: bool = True,
    ) -> None:
        self.accepted = accepted
        self.submit_count = 0
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

        if not self.accepted:
            raise RuntimeError(
                "simulated broker exit failure"
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
    entry_price: float = 100,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T16"
        ),
        signal_id=SignalId(
            "SIG-M07-T16"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T16"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-M07-T16",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )


def make_managed_position(
    *,
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
    with_target: bool = True,
    with_stop: bool = True,
) -> ManagedPosition:
    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-T16"
        ),
        position=make_filled_position(
            quantity=quantity
        ),
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
        stop_loss=(
            StopLossDefinition(
                stop_price=85,
                risk_points=15,
            )
            if with_stop
            else None
        ),
        target=(
            TargetDefinition(
                executable_price=126,
                mapped_target_price=129,
                booking_zone_start=126,
                booking_zone_end=129,
            )
            if with_target
            else None
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def make_decision(
    *,
    trigger: RiskTriggerType,
    quantity: int = 65,
    status: PositionExitDecisionStatus = (
        PositionExitDecisionStatus
        .EXIT_REQUIRED
    ),
) -> PositionExitDecision:
    return PositionExitDecision(
        status=status,
        position_id=FilledPositionId(
            "POS-M07-T16"
        ),
        trigger=trigger,
        quantity=quantity,
        decided_at=NOW,
    )


def make_components(
    position: ManagedPosition,
    *,
    provider: FakeExitProvider | None = None,
):
    registry = PositionRegistry()

    registry.register(
        position
    )

    lifecycle = PositionLifecycleManager(
        registry=registry
    )

    actual_provider = (
        provider
        or FakeExitProvider()
    )

    exit_service = ExitExecutionService(
        provider=actual_provider,
        duplicate_guard=(
            DuplicateOrderGuard()
        ),
        allow_live_exit_orders=True,
    )

    integration = (
        M07ToM06ExitIntegrationService(
            registry=registry,
            lifecycle_manager=lifecycle,
            exit_plan_builder=(
                ExitPlanBuilder(
                    TargetBookingPolicy()
                )
            ),
            exit_execution_service=(
                exit_service
            ),
        )
    )

    return (
        registry,
        actual_provider,
        integration,
    )


def test_target_decision_submits_m06_exit() -> None:
    position = make_managed_position()

    (
        registry,
        provider,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.TARGET
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.submitted is True

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


def test_target_builds_limit_sell() -> None:
    position = make_managed_position()

    (
        _,
        provider,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.TARGET
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.exit_plan is not None

    assert (
        result.exit_plan.reason
        is ExitReason.TARGET
    )

    assert (
        result.exit_plan.order_type
        is ExitOrderType.LIMIT
    )

    # Entry 100
    # mapped target 129
    # near-target rule => 126
    assert (
        result.exit_plan.exit_price
        == 126
    )

    assert provider.last_intent is not None

    assert (
        provider.last_intent.order_type
        is ExitOrderType.LIMIT
    )


def test_target_uses_mapped_option_target() -> None:
    position = make_managed_position()

    (
        _,
        _,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.TARGET
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.exit_plan is not None

    assert (
        result.exit_plan
        .mapped_target_price
        == 129
    )

    assert (
        result.exit_plan
        .mapped_target_price
        != 24650
    )


def test_stop_loss_builds_market_sell() -> None:
    position = make_managed_position()

    (
        _,
        provider,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.STOP_LOSS
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.submitted is True
    assert result.exit_plan is not None

    assert (
        result.exit_plan.reason
        is ExitReason.STOP_LOSS
    )

    assert (
        result.exit_plan.order_type
        is ExitOrderType.MARKET
    )

    assert (
        result.exit_plan.exit_price
        is None
    )

    assert provider.last_intent is not None

    assert (
        provider.last_intent.order_type
        is ExitOrderType.MARKET
    )


def test_force_exit_builds_market_sell() -> None:
    position = make_managed_position()

    (
        _,
        provider,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.FORCE_EXIT
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.submitted is True
    assert result.exit_plan is not None

    assert (
        result.exit_plan.reason
        is ExitReason.FORCE_EXIT
    )

    assert (
        result.exit_plan.order_type
        is ExitOrderType.MARKET
    )

    assert provider.submit_count == 1


def test_partial_stop_exits_only_remaining_quantity() -> None:
    position = make_managed_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    (
        _,
        provider,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.STOP_LOSS,
            quantity=35,
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.exit_plan is not None

    assert (
        result.exit_plan.quantity
        == 35
    )

    assert provider.last_intent is not None

    assert (
        provider.last_intent.quantity
        == 35
    )


def test_partial_force_exit_uses_remaining_quantity() -> None:
    position = make_managed_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    (
        _,
        _,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.FORCE_EXIT,
            quantity=35,
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.exit_plan is not None
    assert result.exit_plan.quantity == 35


def test_decision_quantity_must_equal_open_quantity() -> None:
    position = make_managed_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    (
        _,
        provider,
        integration,
    ) = make_components(
        position
    )

    try:
        integration.execute_decision(
            decision=make_decision(
                trigger=RiskTriggerType.STOP_LOSS,
                quantity=65,
            ),
            execution_mode=ExecutionMode.LIVE,
            requested_at=NOW,
        )

        assert False, (
            "expected quantity validation failure"
        )

    except ValueError as exc:
        assert (
            "exit decision quantity must equal "
            "managed position open quantity"
            in str(exc)
        )

    assert provider.submit_count == 0


def test_target_requires_mapped_target() -> None:
    position = make_managed_position(
        with_target=False
    )

    (
        registry,
        provider,
        integration,
    ) = make_components(
        position
    )

    try:
        integration.execute_decision(
            decision=make_decision(
                trigger=RiskTriggerType.TARGET
            ),
            execution_mode=ExecutionMode.LIVE,
            requested_at=NOW,
        )

        assert False, (
            "expected target validation failure"
        )

    except ValueError as exc:
        assert (
            "TARGET exit requires mapped "
            "option target"
            in str(exc)
        )

    # Deterministic validation happened BEFORE lifecycle lock.
    assert (
        registry.require(
            position.position_id
        ).state
        is ManagedPositionState.OPEN
    )

    assert provider.submit_count == 0


def test_stop_requires_configured_stop() -> None:
    position = make_managed_position(
        with_stop=False
    )

    (
        registry,
        provider,
        integration,
    ) = make_components(
        position
    )

    try:
        integration.execute_decision(
            decision=make_decision(
                trigger=RiskTriggerType.STOP_LOSS
            ),
            execution_mode=ExecutionMode.LIVE,
            requested_at=NOW,
        )

        assert False, (
            "expected stop validation failure"
        )

    except ValueError as exc:
        assert (
            "STOP_LOSS exit requires configured "
            "stop loss"
            in str(exc)
        )

    assert (
        registry.require(
            position.position_id
        ).state
        is ManagedPositionState.OPEN
    )

    assert provider.submit_count == 0


def test_non_actionable_decision_does_not_submit() -> None:
    position = make_managed_position()

    (
        registry,
        provider,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.NONE,
            status=(
                PositionExitDecisionStatus
                .NO_EXIT
            ),
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert (
        result.status
        is M07ExitIntegrationStatus.NO_EXIT
    )

    assert provider.submit_count == 0

    assert (
        registry.require(
            position.position_id
        ).state
        is ManagedPositionState.OPEN
    )


def test_target_marks_target_triggered() -> None:
    position = make_managed_position()

    (
        registry,
        _,
        integration,
    ) = make_components(
        position
    )

    integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.TARGET
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    stored = registry.require(
        position.position_id
    )

    assert stored.target is not None

    assert (
        stored.target.state.value
        == "TRIGGERED"
    )


def test_stop_marks_stop_triggered() -> None:
    position = make_managed_position()

    (
        registry,
        _,
        integration,
    ) = make_components(
        position
    )

    integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.STOP_LOSS
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    stored = registry.require(
        position.position_id
    )

    assert stored.stop_loss is not None

    assert (
        stored.stop_loss.state.value
        == "TRIGGERED"
    )


def test_force_exit_does_not_change_target_or_stop_state() -> None:
    position = make_managed_position()

    (
        registry,
        _,
        integration,
    ) = make_components(
        position
    )

    integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.FORCE_EXIT
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    stored = registry.require(
        position.position_id
    )

    assert stored.target is not None
    assert stored.stop_loss is not None

    assert (
        stored.target.state.value
        == "ARMED"
    )

    assert (
        stored.stop_loss.state.value
        == "ARMED"
    )


def test_m06_rejection_moves_position_to_reconciliation() -> None:
    position = make_managed_position()

    provider = FakeExitProvider(
        accepted=False
    )

    (
        registry,
        _,
        integration,
    ) = make_components(
        position,
        provider=provider,
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.STOP_LOSS
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert (
        result.status
        is M07ExitIntegrationStatus
        .RECONCILIATION_REQUIRED
    )

    stored = registry.require(
        position.position_id
    )

    assert (
        stored.state
        is ManagedPositionState
        .RECONCILIATION_REQUIRED
    )


def test_failed_exit_does_not_return_position_to_open() -> None:
    position = make_managed_position()

    provider = FakeExitProvider(
        accepted=False
    )

    (
        registry,
        _,
        integration,
    ) = make_components(
        position,
        provider=provider,
    )

    integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.STOP_LOSS
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    stored = registry.require(
        position.position_id
    )

    assert (
        stored.state
        is not ManagedPositionState.OPEN
    )


def test_m06_duplicate_guard_blocks_second_sell_path() -> None:
    position = make_managed_position()

    (
        registry,
        provider,
        integration,
    ) = make_components(
        position
    )

    integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.TARGET
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert provider.submit_count == 1

    # M07 lifecycle itself now blocks another clean exit path.
    stored = registry.require(
        position.position_id
    )

    assert (
        stored.state
        is ManagedPositionState.EXIT_PENDING
    )


def test_stop_market_plan_has_no_target_data() -> None:
    position = make_managed_position()

    (
        _,
        _,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.STOP_LOSS
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert result.exit_plan is not None

    assert (
        result.exit_plan.target_plan
        is None
    )

    assert (
        result.exit_plan.mapped_target_price
        is None
    )


def test_integration_preserves_position_identity() -> None:
    position = make_managed_position()

    (
        _,
        _,
        integration,
    ) = make_components(
        position
    )

    result = integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.FORCE_EXIT
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert (
        result.position.position_id
        == position.position_id
    )

    assert result.exit_plan is not None

    assert (
        result.exit_plan.position_id
        == position.position_id
    )


def test_m07_never_calls_broker_directly() -> None:
    """
    The only submission observed by the fake provider must come
    through M06 ExitExecutionService.
    """

    position = make_managed_position()

    (
        _,
        provider,
        integration,
    ) = make_components(
        position
    )

    integration.execute_decision(
        decision=make_decision(
            trigger=RiskTriggerType.FORCE_EXIT
        ),
        execution_mode=ExecutionMode.LIVE,
        requested_at=NOW,
    )

    assert provider.submit_count == 1