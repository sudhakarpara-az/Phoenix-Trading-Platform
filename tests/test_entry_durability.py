from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from src.database.entry_durability import (
    DurableEntryBrokerExecutionProvider,
    SQLAlchemyEntryPersistenceService,
    TradingStatePersistenceError,
)
from src.execution.broker_execution_provider import (
    BrokerCancellationResult,
    BrokerExecutionProvider,
    BrokerOrderSnapshot,
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
from src.execution.order_state_machine import (
    OrderLifecycleState,
    OrderStateMachine,
)
from src.execution.position_exit_types import (
    FilledPosition,
    FilledPositionId,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    StopLossDefinition,
    TargetDefinition,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


NOW = datetime(
    2026,
    8,
    10,
    9,
    21,
)

LATER = datetime(
    2026,
    8,
    10,
    9,
    21,
    1,
)


class FakeRepository:
    def __init__(
        self,
        identity_attribute,
    ):
        self.identity_attribute = (
            identity_attribute
        )
        self.records = {}

    def add(
        self,
        record,
    ):
        identity = getattr(
            record,
            self.identity_attribute,
        )

        if identity in self.records:
            raise RuntimeError(
                f"duplicate: {identity}"
            )

        self.records[
            identity
        ] = record

        return record

    def get(
        self,
        identity,
    ):
        return self.records.get(
            identity
        )

    def update(
        self,
        record,
    ):
        identity = getattr(
            record,
            self.identity_attribute,
        )

        if identity not in self.records:
            raise KeyError(
                identity
            )

        self.records[
            identity
        ] = record

        return record


class FailingOrderRepository(
    FakeRepository
):
    def add(
        self,
        record,
    ):
        del record
        raise RuntimeError(
            "simulated durable order failure"
        )


class FailingPositionRepository(
    FakeRepository
):
    def add(
        self,
        record,
    ):
        del record

        raise RuntimeError(
            "simulated durable position failure"
        )


class RecordingBroker(
    BrokerExecutionProvider
):
    def __init__(
        self,
        *,
        on_submit=None,
        fail=False,
    ):
        self.calls = 0
        self.on_submit = on_submit
        self.fail = fail

    @property
    def broker_name(
        self,
    ) -> str:
        return "DHAN"

    def submit_order(
        self,
        intent,
    ):
        self.calls += 1

        if self.on_submit is not None:
            self.on_submit(
                intent
            )

        if self.fail:
            raise RuntimeError(
                "simulated broker transport failure"
            )

        return ExecutionResult(
            intent_id=(
                intent.intent_id
            ),
            success=True,
            status=(
                BrokerOrderStatus.PENDING
            ),
            broker_reference=(
                BrokerOrderReference(
                    broker_name="DHAN",
                    order_id="BROKER-001",
                )
            ),
            submitted_at=LATER,
        )

    def cancel_order(
        self,
        broker_reference,
    ) -> BrokerCancellationResult:
        raise NotImplementedError

    def get_order_status(
        self,
        broker_reference,
    ) -> BrokerOrderSnapshot:
        raise NotImplementedError


def make_intent():
    contract = OptionContract(
        underlying_symbol="NIFTY 50",
        symbol=(
            "NIFTY50-20260811-24450-CE"
        ),
        security_id="41009",
        option_type=OptionType.CALL,
        strike=24450,
        expiry=date(
            2026,
            8,
            11,
        ),
        lot_size=65,
    )

    quote = OptionQuote(
        ltp=100.0,
        received_at=NOW,
        bid=99.95,
        ask=100.05,
        volume=1000,
        open_interest=50000,
    )

    greeks = OptionGreeks(
        delta=0.64,
        calculated_at=NOW,
    )

    selected_option = SelectedOption(
        candidate=OptionCandidate(
            contract=contract,
            quote=quote,
            greeks=greeks,
        ),
        selected_at=NOW,
        selection_delta_target=0.60,
    )

    signal = TradingSignal(
        signal_id=SignalId(
            "SIG-20260810-41009-K5-000001"
        ),
        trading_date=date(
            2026,
            8,
            10,
        ),
        level=EntryLevel.K5,
        direction=(
            SignalDirection.CALL
        ),
        instrument_security_id="41009",
        instrument_symbol=(
            selected_option.symbol
        ),
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24600.0,
        level_price=100.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=NOW,
    )

    return OrderIntent(
        intent_id=OrderIntentId(
            "ORD-20260810-000001"
        ),
        signal=signal,
        selected_option=(
            selected_option
        ),
        transaction_type=(
            TransactionType.BUY
        ),
        order_type=OrderType.LIMIT,
        quantity=65,
        limit_price=101.0,
        execution_mode=(
            ExecutionMode.LIVE
        ),
        created_at=NOW,
    )


def make_state_machine(
    intent,
    *,
    submitted=True,
):
    machine = OrderStateMachine()

    machine.register(
        intent
    )

    if submitted:
        machine.transition(
            intent.intent_id,
            OrderLifecycleState.VALIDATED,
            NOW,
        )

        machine.transition(
            intent.intent_id,
            OrderLifecycleState.SUBMITTED,
            NOW,
        )

    return machine


def make_managed_position(
    *,
    intent,
    broker_reference,
    filled_at,
):
    filled = FilledPosition(
        position_id=FilledPositionId(
            "POS-20260810-000001"
        ),
        signal_id=(
            intent.signal.signal_id
        ),
        entry_intent_id=(
            intent.intent_id
        ),
        entry_broker_reference=(
            broker_reference
        ),
        selected_option=(
            intent.selected_option
        ),
        level=(
            intent.signal.level
        ),
        quantity=(
            intent.quantity
        ),
        entry_price=100.65,
        filled_at=filled_at,
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK:POS-20260810-000001"
        ),
        position=filled,
        open_quantity=(
            intent.quantity
        ),
        closed_quantity=0,
        realized_pnl=0.0,
        state=ManagedPositionState.OPEN,
        stop_loss=StopLossDefinition(
            stop_price=85.65,
            risk_points=15.0,
        ),
        target=TargetDefinition(
            executable_price=127.65,
            mapped_target_price=130.65,
            booking_zone_start=127.65,
            booking_zone_end=130.65,
        ),
        created_at=filled_at,
        updated_at=filled_at,
    )


def make_persistence(
    *,
    order_repository=None,
):
    signal_repository = FakeRepository(
        "signal_id"
    )

    option_repository = FakeRepository(
        "selection_id"
    )

    if order_repository is None:
        order_repository = FakeRepository(
            "order_intent_id"
        )

    persistence = (
        SQLAlchemyEntryPersistenceService(
            runtime_id="RUNTIME-001",
            signal_repository=(
                signal_repository
            ),
            option_selection_repository=(
                option_repository
            ),
            order_repository=(
                order_repository
            ),
        )
    )

    return (
        persistence,
        signal_repository,
        option_repository,
        order_repository,
    )


def test_pre_broker_persistence_maps_exact_domain_state():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        signal_repository,
        option_repository,
        order_repository,
    ) = make_persistence()

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    signal = signal_repository.get(
        intent.signal.signal_id.value
    )

    selection = option_repository.get(
        intent.signal.signal_id.value
    )

    order = order_repository.get(
        intent.intent_id.value
    )

    assert signal is not None
    assert signal.runtime_id == "RUNTIME-001"
    assert signal.signal_type == "BUY_CALL"
    assert signal.option_type == "CALL"
    assert signal.level == "K5"
    assert signal.quantity == 65
    assert signal.status == "CREATED"
    assert signal.reason == "CROSS_UP"

    assert selection is not None
    assert (
        selection.selection_id
        == intent.signal.signal_id.value
    )
    assert selection.signal_id == (
        intent.signal.signal_id.value
    )
    assert selection.security_id == "41009"
    assert selection.option_type == "CALL"
    assert selection.strike == 24450
    assert selection.lot_size == 65
    assert selection.delta == 0.64
    assert selection.target_delta == 0.60

    assert order is not None
    assert order.status == "SUBMITTED"
    assert order.side == "BUY"
    assert order.order_type == "LIMIT"
    assert order.reason == "ENTRY"
    assert order.execution_mode == "LIVE"
    assert order.broker_name == "DHAN"
    assert order.broker_order_id is None
    assert order.filled_quantity == 0


def test_wrapper_persists_submitted_before_broker_call():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        _,
        _,
        order_repository,
    ) = make_persistence()

    observed = {}

    def inspect_before_broker(
        submitted_intent,
    ):
        order = order_repository.get(
            submitted_intent
            .intent_id
            .value
        )
        assert order is not None

        observed["exists"] = (
            order is not None
        )

        observed["status"] = (
            order.status
        )

    delegate = RecordingBroker(
        on_submit=inspect_before_broker
    )

    provider = (
        DurableEntryBrokerExecutionProvider(
            delegate=delegate,
            persistence=persistence,
            state_machine=machine,
        )
    )

    result = provider.submit_order(
        intent
    )

    assert delegate.calls == 1
    assert observed == {
        "exists": True,
        "status": "SUBMITTED",
    }

    assert (
        result.broker_reference
        is not None
    )

    durable_order = (
        order_repository.get(
            intent.intent_id.value
        )
    )
    assert durable_order is not None

    assert (
        durable_order.broker_order_id
        == "BROKER-001"
    )

    # M06 lifecycle mapping occurs after provider return.
    assert durable_order.status == "SUBMITTED"


def test_persistence_failure_prevents_broker_call():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        _,
        _,
        _,
    ) = make_persistence(
        order_repository=(
            FailingOrderRepository(
                "order_intent_id"
            )
        )
    )

    delegate = RecordingBroker()

    provider = (
        DurableEntryBrokerExecutionProvider(
            delegate=delegate,
            persistence=persistence,
            state_machine=machine,
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "simulated durable "
            "order failure"
        ),
    ):
        provider.submit_order(
            intent
        )

    assert delegate.calls == 0


def test_existing_durable_order_blocks_resubmission():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        _,
        _,
        _,
    ) = make_persistence()

    snapshot = machine.snapshot(
        intent.intent_id
    )

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=snapshot,
    )

    delegate = RecordingBroker()

    provider = (
        DurableEntryBrokerExecutionProvider(
            delegate=delegate,
            persistence=persistence,
            state_machine=machine,
        )
    )

    with pytest.raises(
        TradingStatePersistenceError,
        match="resubmission blocked",
    ):
        provider.submit_order(
            intent
        )

    assert delegate.calls == 0


def test_non_submitted_lifecycle_never_calls_broker():
    intent = make_intent()

    machine = make_state_machine(
        intent,
        submitted=False,
    )

    (
        persistence,
        _,
        _,
        _,
    ) = make_persistence()

    delegate = RecordingBroker()

    provider = (
        DurableEntryBrokerExecutionProvider(
            delegate=delegate,
            persistence=persistence,
            state_machine=machine,
        )
    )

    with pytest.raises(
        TradingStatePersistenceError,
        match="SUBMITTED",
    ):
        provider.submit_order(
            intent
        )

    assert delegate.calls == 0


def test_delegate_exception_leaves_durable_submitted_order():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        _,
        _,
        order_repository,
    ) = make_persistence()

    delegate = RecordingBroker(
        fail=True
    )

    provider = (
        DurableEntryBrokerExecutionProvider(
            delegate=delegate,
            persistence=persistence,
            state_machine=machine,
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "simulated broker "
            "transport failure"
        ),
    ):
        provider.submit_order(
            intent
        )

    assert delegate.calls == 1

    durable_order = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert durable_order is not None
    assert durable_order.status == "SUBMITTED"
    assert durable_order.broker_order_id is None

def test_authoritative_fill_facts_persist_before_terminal_order():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        _,
        _,
        order_repository,
    ) = make_persistence()

    submitted_snapshot = (
        machine.snapshot(
            intent.intent_id
        )
    )

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            submitted_snapshot
        ),
    )

    result = ExecutionResult(
        intent_id=intent.intent_id,
        success=True,
        status=BrokerOrderStatus.PENDING,
        broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="BROKER-FILL-001",
            )
        ),
        submitted_at=LATER,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
    )

    filled_at = (
        LATER
        + timedelta(seconds=1)
    )

    reference = result.broker_reference
    assert reference is not None

    broker_snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=intent.quantity,
        filled_quantity=intent.quantity,
        average_price=100.65,
        updated_at=filled_at,
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FILLED,
        filled_at,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    durable_order = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert durable_order is not None

    assert (
        durable_order.status
        == OrderLifecycleState.SUBMITTED.value
    )

    assert (
        durable_order.filled_quantity
        == intent.quantity
    )

    assert (
        durable_order.average_fill_price
        == 100.65
    )

    assert (
        durable_order.updated_at
        == filled_at
    )

    assert durable_order.position_id is None


def test_authoritative_fill_requires_m06_filled_lifecycle():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        _,
        _,
        order_repository,
    ) = make_persistence()

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    result = ExecutionResult(
        intent_id=intent.intent_id,
        success=True,
        status=BrokerOrderStatus.PENDING,
        broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="BROKER-FILL-002",
            )
        ),
        submitted_at=LATER,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
    )

    reference = result.broker_reference
    assert reference is not None

    broker_snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=intent.quantity,
        filled_quantity=intent.quantity,
        average_price=100.65,
        updated_at=(
            LATER
            + timedelta(seconds=1)
        ),
    )

    with pytest.raises(
        TradingStatePersistenceError,
        match="M06 FILLED",
    ):
        persistence.persist_broker_execution_result(
            intent=intent,
            result=result,
            broker_snapshot=broker_snapshot,
            lifecycle_snapshot=(
                machine.snapshot(
                    intent.intent_id
                )
            ),
        )

    durable_order = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert durable_order is not None
    assert durable_order.filled_quantity == 0
    assert durable_order.average_fill_price is None

    assert (
        durable_order.status
        == OrderLifecycleState.SUBMITTED.value
    )


def test_managed_position_maps_to_durable_position_record():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        _,
        signal_repository,
        option_repository,
        order_repository,
    ) = make_persistence()

    position_repository = FakeRepository(
        "position_id"
    )

    persistence = SQLAlchemyEntryPersistenceService(
        runtime_id="RUNTIME-001",
        signal_repository=signal_repository,
        option_selection_repository=(
            option_repository
        ),
        order_repository=order_repository,
        position_repository=(
            position_repository
        ),
    )

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="BROKER-POS-001",
    )

    result = ExecutionResult(
        intent_id=intent.intent_id,
        success=True,
        status=BrokerOrderStatus.PENDING,
        broker_reference=reference,
        submitted_at=LATER,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
    )

    filled_at = (
        LATER
        + timedelta(seconds=1)
    )

    broker_snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=intent.quantity,
        filled_quantity=intent.quantity,
        average_price=100.65,
        updated_at=filled_at,
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FILLED,
        filled_at,
    )

    lifecycle_snapshot = (
        machine.snapshot(
            intent.intent_id
        )
    )

    # First crash-safe boundary:
    # authoritative fill facts become durable.
    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
    )

    order_before_position = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert order_before_position is not None

    assert (
        order_before_position.filled_quantity
        == intent.quantity
    )

    assert (
        order_before_position.average_fill_price
        == 100.65
    )

    assert (
        order_before_position.status
        == OrderLifecycleState.SUBMITTED.value
    )

    managed = make_managed_position(
        intent=intent,
        broker_reference=reference,
        filled_at=filled_at,
    )

    # Second crash-safe boundary:
    # exact M07 ManagedPosition becomes durable.
    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
        managed_position=managed,
    )

    durable = position_repository.get(
        managed.position_id.value
    )

    assert durable is not None

    assert (
        durable.position_id
        == managed.position_id.value
    )

    assert (
        durable.risk_id
        == managed.risk_id.value
    )

    assert durable.runtime_id == "RUNTIME-001"

    assert (
        durable.signal_id
        == intent.signal.signal_id.value
    )

    assert (
        durable.entry_order_intent_id
        == intent.intent_id.value
    )

    assert (
        durable.security_id
        == intent.selected_option.security_id
    )

    assert (
        durable.symbol
        == intent.selected_option.symbol
    )

    assert durable.option_type == "CALL"
    assert durable.level == "K5"

    assert durable.original_quantity == 65
    assert durable.open_quantity == 65
    assert durable.closed_quantity == 0

    assert durable.entry_price == 100.65
    assert durable.realized_pnl == 0.0
    assert durable.state == "OPEN"

    assert durable.stop_price == 85.65
    assert durable.stop_risk_points == 15.0
    assert durable.stop_state == "ARMED"

    assert (
        durable.executable_target_price
        == 127.65
    )

    assert (
        durable.mapped_target_price
        == 130.65
    )

    assert (
        durable.booking_zone_start
        == 127.65
    )

    assert (
        durable.booking_zone_end
        == 130.65
    )

    assert durable.target_state == "ARMED"

    assert durable.opened_at == filled_at
    assert durable.updated_at == filled_at
    assert durable.closed_at is None

    durable_order = order_repository.get(
        intent.intent_id.value
    )

    assert durable_order is not None

    # Still recovery-visible.
    assert (
        durable_order.status
        == OrderLifecycleState.SUBMITTED.value
    )

    # Terminal linkage is deliberately later.
    assert durable_order.position_id is None


def test_position_failure_keeps_durable_order_recovery_visible():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        _,
        signal_repository,
        option_repository,
        order_repository,
    ) = make_persistence()

    position_repository = (
        FailingPositionRepository(
            "position_id"
        )
    )

    persistence = SQLAlchemyEntryPersistenceService(
        runtime_id="RUNTIME-001",
        signal_repository=signal_repository,
        option_selection_repository=(
            option_repository
        ),
        order_repository=order_repository,
        position_repository=(
            position_repository
        ),
    )

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="BROKER-POS-FAIL",
    )

    result = ExecutionResult(
        intent_id=intent.intent_id,
        success=True,
        status=BrokerOrderStatus.PENDING,
        broker_reference=reference,
        submitted_at=LATER,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
    )

    filled_at = (
        LATER
        + timedelta(seconds=1)
    )

    broker_snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=intent.quantity,
        filled_quantity=intent.quantity,
        average_price=100.65,
        updated_at=filled_at,
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FILLED,
        filled_at,
    )

    lifecycle_snapshot = machine.snapshot(
        intent.intent_id
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
    )

    managed = make_managed_position(
        intent=intent,
        broker_reference=reference,
        filled_at=filled_at,
    )

    with pytest.raises(
        RuntimeError,
        match="simulated durable position failure",
    ):
        persistence.persist_broker_execution_result(
            intent=intent,
            result=result,
            broker_snapshot=broker_snapshot,
            lifecycle_snapshot=(
                lifecycle_snapshot
            ),
            managed_position=managed,
        )

    durable_order = order_repository.get(
        intent.intent_id.value
    )

    assert durable_order is not None

    # Broker fill truth survived the failed position transaction.
    assert (
        durable_order.filled_quantity
        == intent.quantity
    )

    assert (
        durable_order.average_fill_price
        == 100.65
    )

    # Critical crash/recovery invariant.
    assert (
        durable_order.status
        == OrderLifecycleState.SUBMITTED.value
    )

    assert durable_order.position_id is None

    assert (
        position_repository.get(
            managed.position_id.value
        )
        is None
    )


def test_terminal_filled_order_occurs_only_after_durable_position():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        _,
        signal_repository,
        option_repository,
        order_repository,
    ) = make_persistence()

    position_repository = FakeRepository(
        "position_id"
    )

    persistence = SQLAlchemyEntryPersistenceService(
        runtime_id="RUNTIME-001",
        signal_repository=signal_repository,
        option_selection_repository=(
            option_repository
        ),
        order_repository=order_repository,
        position_repository=(
            position_repository
        ),
    )

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="BROKER-TERMINAL-001",
    )

    result = ExecutionResult(
        intent_id=intent.intent_id,
        success=True,
        status=BrokerOrderStatus.PENDING,
        broker_reference=reference,
        submitted_at=LATER,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
    )

    filled_at = (
        LATER
        + timedelta(seconds=1)
    )

    broker_snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=intent.quantity,
        filled_quantity=intent.quantity,
        average_price=100.65,
        updated_at=filled_at,
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FILLED,
        filled_at,
    )

    lifecycle_snapshot = (
        machine.snapshot(
            intent.intent_id
        )
    )

    # --------------------------------------------------------
    # Crash boundary 1:
    # broker fill facts durable, order still unresolved.
    # --------------------------------------------------------

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
    )

    managed = make_managed_position(
        intent=intent,
        broker_reference=reference,
        filled_at=filled_at,
    )

    # --------------------------------------------------------
    # Crash boundary 2:
    # PositionRecord durable, order still recovery-visible.
    # --------------------------------------------------------

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
        managed_position=managed,
    )

    durable_position = (
        position_repository.get(
            managed.position_id.value
        )
    )

    assert durable_position is not None

    before_terminal = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert before_terminal is not None

    assert (
        before_terminal.status
        == OrderLifecycleState.SUBMITTED.value
    )

    assert before_terminal.position_id is None

    # --------------------------------------------------------
    # Crash boundary 3:
    # only now may the durable order become terminal FILLED.
    # --------------------------------------------------------

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
        managed_position=managed,
        terminalize_order=True,
    )

    durable_order = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert durable_order is not None

    assert (
        durable_order.status
        == OrderLifecycleState.FILLED.value
    )

    assert (
        durable_order.position_id
        == managed.position_id.value
    )

    assert (
        durable_order.filled_quantity
        == intent.quantity
    )

    assert (
        durable_order.average_fill_price
        == managed.entry_price
    )

    # Position remains independently durable.
    durable_position_after = (
        position_repository.get(
            managed.position_id.value
        )
    )

    assert durable_position_after is not None

    assert (
        durable_position_after.entry_order_intent_id
        == intent.intent_id.value
    )


def test_terminalization_requires_managed_position():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        persistence,
        _,
        _,
        order_repository,
    ) = make_persistence()

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="BROKER-TERMINAL-002",
    )

    result = ExecutionResult(
        intent_id=intent.intent_id,
        success=True,
        status=BrokerOrderStatus.PENDING,
        broker_reference=reference,
        submitted_at=LATER,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
    )

    filled_at = (
        LATER
        + timedelta(seconds=1)
    )

    broker_snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=intent.quantity,
        filled_quantity=intent.quantity,
        average_price=100.65,
        updated_at=filled_at,
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FILLED,
        filled_at,
    )

    lifecycle_snapshot = (
        machine.snapshot(
            intent.intent_id
        )
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
    )

    with pytest.raises(
        TypeError,
        match="terminalize_order requires managed_position",
    ):
        persistence.persist_broker_execution_result(
            intent=intent,
            result=result,
            broker_snapshot=broker_snapshot,
            lifecycle_snapshot=(
                lifecycle_snapshot
            ),
            terminalize_order=True,
        )

    durable_order = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert durable_order is not None

    assert (
        durable_order.status
        == OrderLifecycleState.SUBMITTED.value
    )

    assert durable_order.position_id is None


def test_terminal_filled_order_replay_is_idempotent():
    intent = make_intent()

    machine = make_state_machine(
        intent
    )

    (
        _,
        signal_repository,
        option_repository,
        order_repository,
    ) = make_persistence()

    position_repository = FakeRepository(
        "position_id"
    )

    persistence = SQLAlchemyEntryPersistenceService(
        runtime_id="RUNTIME-001",
        signal_repository=signal_repository,
        option_selection_repository=(
            option_repository
        ),
        order_repository=order_repository,
        position_repository=(
            position_repository
        ),
    )

    persistence.persist_pre_broker_submission(
        intent=intent,
        broker_name="DHAN",
        lifecycle_snapshot=(
            machine.snapshot(
                intent.intent_id
            )
        ),
    )

    reference = BrokerOrderReference(
        broker_name="DHAN",
        order_id="BROKER-REPLAY-001",
    )

    result = ExecutionResult(
        intent_id=intent.intent_id,
        success=True,
        status=BrokerOrderStatus.PENDING,
        broker_reference=reference,
        submitted_at=LATER,
    )

    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
    )

    filled_at = (
        LATER
        + timedelta(seconds=1)
    )

    broker_snapshot = BrokerOrderSnapshot(
        broker_reference=reference,
        status=BrokerOrderStatus.FILLED,
        quantity=intent.quantity,
        filled_quantity=intent.quantity,
        average_price=100.65,
        updated_at=filled_at,
    )

    machine.transition(
        intent.intent_id,
        OrderLifecycleState.FILLED,
        filled_at,
    )

    lifecycle_snapshot = (
        machine.snapshot(
            intent.intent_id
        )
    )

    managed = make_managed_position(
        intent=intent,
        broker_reference=reference,
        filled_at=filled_at,
    )

    # First complete durable terminalization.
    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
        managed_position=managed,
        terminalize_order=True,
    )

    first_order = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert first_order is not None

    assert (
        first_order.status
        == OrderLifecycleState.FILLED.value
    )

    assert (
        first_order.position_id
        == managed.position_id.value
    )

    # Simulate T14 replay after a failure/crash occurring after
    # durable FILLED but before P&L or M04 completion.
    persistence.persist_broker_execution_result(
        intent=intent,
        result=result,
        broker_snapshot=broker_snapshot,
        lifecycle_snapshot=(
            lifecycle_snapshot
        ),
        managed_position=managed,
        terminalize_order=True,
    )

    replayed_order = (
        order_repository.get(
            intent.intent_id.value
        )
    )

    assert replayed_order is not None

    assert (
        replayed_order.status
        == OrderLifecycleState.FILLED.value
    )

    assert (
        replayed_order.position_id
        == managed.position_id.value
    )

    assert (
        replayed_order.filled_quantity
        == intent.quantity
    )

    assert (
        replayed_order.average_fill_price
        == managed.entry_price
    )

    durable_position = (
        position_repository.get(
            managed.position_id.value
        )
    )

    assert durable_position is not None

    assert (
        durable_position.entry_order_intent_id
        == intent.intent_id.value
    )
