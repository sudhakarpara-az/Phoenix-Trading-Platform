from datetime import date, datetime
from decimal import Decimal

import pytest

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
    ExecutionMode,
    ExecutionResult,
)
from src.execution.m06_entry_runtime_adapter import (
    M06EntryRuntimeAdapter,
)
from src.execution.order_eligibility_validator import (
    OrderEligibilityValidator,
)
from src.execution.order_pricing_policy import (
    OrderPricingPolicy,
)
from src.execution.order_state_machine import (
    OrderStateMachine,
)
from src.execution.quantity_policy import (
    QuantityPolicy,
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


TRADING_DATE = date(
    2026,
    8,
    7,
)

NOW = datetime(
    2026,
    8,
    7,
    10,
    0,
)

EXPIRY = date(
    2026,
    8,
    11,
)

SECURITY_ID = "41009"
SYMBOL = "NIFTY50-20260811-24450-CE"


class FakeBroker(
    BrokerExecutionProvider
):
    def __init__(self) -> None:
        self.submit_count = 0

        self.last_intent = None

        self.reference = (
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-T14-001",
            )
        )

    @property
    def broker_name(self) -> str:
        return "DHAN"

    def submit_order(
        self,
        intent,
    ) -> ExecutionResult:
        self.submit_count += 1
        self.last_intent = intent

        return ExecutionResult(
            intent_id=intent.intent_id,
            success=True,
            status=BrokerOrderStatus.OPEN,
            broker_reference=self.reference,
            submitted_at=intent.created_at,
        )

    def cancel_order(
        self,
        broker_reference,
    ) -> BrokerCancellationResult:
        return BrokerCancellationResult(
            broker_reference=broker_reference,
            success=True,
            status=BrokerOrderStatus.CANCELLED,
            cancelled_at=NOW,
        )

    def get_order_status(
        self,
        broker_reference,
    ) -> BrokerOrderSnapshot:
        return BrokerOrderSnapshot(
            broker_reference=broker_reference,
            status=BrokerOrderStatus.OPEN,
            quantity=65,
            filled_quantity=0,
            average_price=None,
            updated_at=NOW,
        )


def make_selected_option(
    *,
    lot_size: int = 65,
    ltp: float = 100.0,
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=SYMBOL,
                security_id=SECURITY_ID,
                option_type=OptionType.CALL,
                strike=24450.0,
                expiry=EXPIRY,
                lot_size=lot_size,
            ),
            quote=OptionQuote(
                ltp=ltp,
                bid=ltp - 0.05,
                ask=ltp + 0.05,
                volume=10000,
                open_interest=50000,
                received_at=NOW,
            ),
            greeks=OptionGreeks(
                delta=0.60,
                calculated_at=NOW,
            ),
        ),
        selected_at=NOW,
        selection_delta_target=0.60,
    )


def make_signal(
    *,
    generated_at: datetime = NOW,
) -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId(
            "SIG-T14-ENTRY-001"
        ),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        instrument_security_id=SECURITY_ID,
        instrument_symbol=SYMBOL,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=100.0,
        level_price=100.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=generated_at,
    )


def make_service(
    broker: FakeBroker,
) -> ExecutionService:
    return ExecutionService(
        pricing_policy=OrderPricingPolicy(),
        quantity_policy=QuantityPolicy(),
        eligibility_validator=(
            OrderEligibilityValidator()
        ),
        state_machine=OrderStateMachine(),
        broker_provider=broker,
        allow_live_orders=True,
    )


def test_adapter_uses_exact_m06_policy_instances() -> None:
    broker = FakeBroker()

    service = make_service(
        broker
    )

    adapter = M06EntryRuntimeAdapter(
        execution_service=service
    )

    assert (
        adapter.sizing_policy.pricing_policy
        is service.pricing_policy
    )

    assert (
        adapter.sizing_policy.quantity_policy
        is service.quantity_policy
    )


def test_default_sizing_is_one_contract_lot() -> None:
    broker = FakeBroker()

    adapter = M06EntryRuntimeAdapter(
        execution_service=(
            make_service(
                broker
            )
        )
    )

    sizing = adapter.calculate_sizing(
        selected_option=(
            make_selected_option(
                lot_size=65,
                ltp=100.0,
            )
        )
    )

    assert sizing.preferred_lots == 1
    assert sizing.lot_size == 65
    assert sizing.requested_quantity == 65

    assert (
        sizing.pricing.limit_price
        == 101.0
    )

    assert (
        sizing.required_cash
        == Decimal("6565.0")
    )


def test_preferred_lots_use_dynamic_contract_lot_size() -> None:
    broker = FakeBroker()

    adapter = M06EntryRuntimeAdapter(
        execution_service=(
            make_service(
                broker
            )
        ),
        preferred_lots=2,
    )

    sizing = adapter.calculate_sizing(
        selected_option=(
            make_selected_option(
                lot_size=75,
                ltp=100.02,
            )
        )
    )

    assert sizing.requested_quantity == 150
    assert sizing.pricing.limit_price == 101.05

    assert (
        sizing.required_cash
        == Decimal("15157.50")
    )


def test_live_execution_uses_precalculated_quantity_and_price() -> None:
    broker = FakeBroker()

    service = make_service(
        broker
    )

    adapter = M06EntryRuntimeAdapter(
        execution_service=service,
        preferred_lots=2,
    )

    option = make_selected_option(
        lot_size=65,
        ltp=100.0,
    )

    sizing = adapter.calculate_sizing(
        selected_option=option
    )

    result = adapter.execute_entry(
        signal=make_signal(),
        selected_option=option,
        dry_run=False,
        requested_at=NOW,
    )

    assert result.accepted is True
    assert result.submitted is True

    assert result.intent is not None

    assert (
        result.intent.execution_mode
        is ExecutionMode.LIVE
    )

    assert (
        result.intent.quantity
        == sizing.requested_quantity
        == 130
    )

    assert (
        result.intent.limit_price
        == sizing.pricing.limit_price
        == 101.0
    )

    assert broker.submit_count == 1


def test_dry_run_never_calls_live_broker() -> None:
    broker = FakeBroker()

    adapter = M06EntryRuntimeAdapter(
        execution_service=(
            make_service(
                broker
            )
        )
    )

    result = adapter.execute_entry(
        signal=make_signal(),
        selected_option=(
            make_selected_option()
        ),
        dry_run=True,
        requested_at=NOW,
    )

    assert result.accepted is True
    assert result.submitted is True

    assert result.intent is not None

    assert (
        result.intent.execution_mode
        is ExecutionMode.DRY_RUN
    )

    assert broker.submit_count == 0


def test_exact_signal_contract_identity_survives_adapter() -> None:
    broker = FakeBroker()

    adapter = M06EntryRuntimeAdapter(
        execution_service=(
            make_service(
                broker
            )
        )
    )

    signal = make_signal()
    option = make_selected_option()

    result = adapter.execute_entry(
        signal=signal,
        selected_option=option,
        dry_run=False,
        requested_at=NOW,
    )

    assert result.intent is not None

    assert (
        result.intent.signal
        is signal
    )

    assert (
        result.intent.selected_option
        is option
    )

    assert (
        result.intent.signal
        .instrument_security_id
        == SECURITY_ID
    )

    assert (
        result.intent.selected_option
        .security_id
        == SECURITY_ID
    )


def test_1515_entry_is_rejected_before_broker_submission() -> None:
    broker = FakeBroker()

    adapter = M06EntryRuntimeAdapter(
        execution_service=(
            make_service(
                broker
            )
        )
    )

    at_force_exit = datetime(
        2026,
        8,
        7,
        15,
        15,
    )

    result = adapter.execute_entry(
        signal=make_signal(
            generated_at=at_force_exit
        ),
        selected_option=(
            make_selected_option()
        ),
        dry_run=False,
        requested_at=at_force_exit,
    )

    assert result.accepted is False
    assert result.submitted is False
    assert broker.submit_count == 0


@pytest.mark.parametrize(
    "preferred_lots",
    [
        0,
        -1,
    ],
)
def test_non_positive_preferred_lots_are_rejected(
    preferred_lots,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            "preferred_lots must be greater than zero"
        ),
    ):
        M06EntryRuntimeAdapter(
            execution_service=(
                make_service(
                    FakeBroker()
                )
            ),
            preferred_lots=preferred_lots,
        )


@pytest.mark.parametrize(
    "preferred_lots",
    [
        True,
        1.5,
        "1",
    ],
)
def test_non_integer_preferred_lots_are_rejected(
    preferred_lots,
) -> None:
    with pytest.raises(
        TypeError,
        match=(
            "preferred_lots must be an integer"
        ),
    ):
        M06EntryRuntimeAdapter(
            execution_service=(
                make_service(
                    FakeBroker()
                )
            ),
            preferred_lots=preferred_lots,
        )


def test_invalid_runtime_argument_types_fail_before_m06() -> None:
    broker = FakeBroker()

    adapter = M06EntryRuntimeAdapter(
        execution_service=(
            make_service(
                broker
            )
        )
    )

    with pytest.raises(
        TypeError,
        match="dry_run must be bool",
    ):
        adapter.execute_entry(
            signal=make_signal(),
            selected_option=(
                make_selected_option()
            ),
            dry_run=1,
            requested_at=NOW,
        )

    with pytest.raises(
        TypeError,
        match="requested_at must be a datetime",
    ):
        adapter.execute_entry(
            signal=make_signal(),
            selected_option=(
                make_selected_option()
            ),
            dry_run=False,
            requested_at="2026-08-07",
        )

    assert broker.submit_count == 0
