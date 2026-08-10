from __future__ import annotations

from datetime import date, datetime

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