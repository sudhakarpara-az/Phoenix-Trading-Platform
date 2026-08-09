from datetime import (
    date,
    datetime,
    timedelta,
)

import pytest

from src.execution.execution_types import (
    BrokerOrderReference,
    OrderIntentId,
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
from src.risk.option_position_price_monitor import (
    OptionPositionPriceMonitor,
    OptionPriceTick,
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
    StopLossState,
)
from src.risk.stop_loss_trigger_monitor import (
    StopLossTriggerMonitor,
    StopLossTriggerStatus,
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


def make_filled_position() -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T08"
        ),
        signal_id=SignalId(
            "SIG-M07-T08"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T08"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="DHAN-M07-T08",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=65,
        entry_price=100,
        filled_at=NOW,
    )


def make_stop(
    *,
    state: StopLossState = (
        StopLossState.ARMED
    ),
) -> StopLossDefinition:
    return StopLossDefinition(
        stop_price=85,
        risk_points=15,
        state=state,
    )


def make_managed_position(
    *,
    stop_loss: StopLossDefinition | None = None,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
    open_quantity: int = 65,
    closed_quantity: int = 0,
) -> ManagedPosition:
    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-T08"
        ),
        position=make_filled_position(),
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
        stop_loss=(
            make_stop()
            if stop_loss is None
            else stop_loss
        ),
        target=None,
        created_at=NOW,
        updated_at=NOW,
    )


def make_position_without_stop() -> ManagedPosition:
    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-T08"
        ),
        position=make_filled_position(),
        open_quantity=65,
        closed_quantity=0,
        realized_pnl=0,
        state=ManagedPositionState.OPEN,
        stop_loss=None,
        target=None,
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

    stop_monitor = (
        StopLossTriggerMonitor(
            price_monitor=price_monitor,
            max_price_age=timedelta(
                seconds=5
            ),
        )
    )

    return (
        registry,
        price_monitor,
        stop_monitor,
    )


def push_price(
    price_monitor,
    *,
    ltp: float,
    received_at: datetime = NOW,
):
    return price_monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=ltp,
            received_at=received_at,
        )
    )


def test_above_stop_is_not_triggered() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85.05,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus.NOT_TRIGGERED
    )

    assert result.triggered is False

    assert (
        result.trigger
        is RiskTriggerType.NONE
    )


def test_exact_stop_price_triggers() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus.TRIGGERED
    )

    assert result.triggered is True

    assert (
        result.trigger
        is RiskTriggerType.STOP_LOSS
    )

    assert result.current_ltp == 85
    assert result.stop_price == 85
    assert result.risk_points == 15


def test_below_stop_price_triggers() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=84,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert result.triggered is True

    assert (
        result.status
        is StopLossTriggerStatus.TRIGGERED
    )


def test_large_gap_below_stop_triggers() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=70,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert result.triggered is True

    assert result.current_ltp == 70


def test_trigger_is_emitted_only_once() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85,
    )

    first = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    second = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert first.triggered is True

    assert (
        second.status
        is StopLossTriggerStatus
        .ALREADY_TRIGGERED
    )

    assert second.triggered is False


def test_lower_future_tick_does_not_duplicate_trigger() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85,
    )

    first = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    later = (
        NOW
        + timedelta(seconds=1)
    )

    push_price(
        price_monitor,
        ltp=80,
        received_at=later,
    )

    second = stop_monitor.evaluate(
        position=position,
        evaluated_at=later,
    )

    assert first.triggered is True

    assert (
        second.status
        is StopLossTriggerStatus
        .ALREADY_TRIGGERED
    )


def test_no_price_returns_price_not_available() -> None:
    position = make_managed_position()

    (
        _,
        _,
        stop_monitor,
    ) = make_components(
        position
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus
        .PRICE_NOT_AVAILABLE
    )

    assert result.current_ltp is None


def test_stale_price_does_not_trigger() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=80,
        received_at=NOW,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=(
            NOW
            + timedelta(seconds=10)
        ),
    )

    assert (
        result.status
        is StopLossTriggerStatus.STALE_PRICE
    )

    assert result.triggered is False


def test_price_at_exact_freshness_boundary_can_trigger() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85,
        received_at=NOW,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=(
            NOW
            + timedelta(seconds=5)
        ),
    )

    assert result.triggered is True


def test_closed_position_does_not_trigger() -> None:
    position = make_managed_position(
        state=ManagedPositionState.CLOSED,
        open_quantity=0,
        closed_quantity=65,
    )

    (
        _,
        _,
        stop_monitor,
    ) = make_components(
        position
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus
        .POSITION_CLOSED
    )

    assert result.triggered is False


def test_no_stop_returns_no_stop_loss() -> None:
    position = make_position_without_stop()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=80,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus
        .NO_STOP_LOSS
    )


def test_disabled_stop_does_not_trigger() -> None:
    position = make_managed_position(
        stop_loss=make_stop(
            state=StopLossState.DISABLED
        )
    )

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=80,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus
        .STOP_LOSS_DISABLED
    )


def test_domain_stop_already_triggered_is_not_retriggered() -> None:
    position = make_managed_position(
        stop_loss=make_stop(
            state=StopLossState.TRIGGERED
        )
    )

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=80,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus
        .ALREADY_TRIGGERED
    )


def test_partial_position_can_trigger_stop() -> None:
    position = make_managed_position(
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
        open_quantity=35,
        closed_quantity=30,
    )

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert result.triggered is True


def test_exit_pending_with_triggered_stop_does_not_duplicate() -> None:
    position = make_managed_position(
        stop_loss=make_stop(
            state=StopLossState.TRIGGERED
        ),
        state=(
            ManagedPositionState.EXIT_PENDING
        ),
    )

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=80,
    )

    result = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is StopLossTriggerStatus
        .ALREADY_TRIGGERED
    )


def test_has_triggered_after_event() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85,
    )

    stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert stop_monitor.has_triggered(
        position.position_id
    ) is True


def test_above_stop_does_not_mark_triggered() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=90,
    )

    stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert stop_monitor.has_triggered(
        position.position_id
    ) is False


def test_reset_position_allows_future_trigger() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85,
    )

    first = stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert first.triggered is True

    assert stop_monitor.reset_position(
        position.position_id
    ) is True

    later = (
        NOW
        + timedelta(seconds=1)
    )

    push_price(
        price_monitor,
        ltp=84,
        received_at=later,
    )

    second = stop_monitor.evaluate(
        position=position,
        evaluated_at=later,
    )

    assert second.triggered is True


def test_reset_unknown_position_returns_false() -> None:
    position = make_managed_position()

    (
        _,
        _,
        stop_monitor,
    ) = make_components(
        position
    )

    assert stop_monitor.reset_position(
        position.position_id
    ) is False


def test_clear_removes_trigger_memory() -> None:
    position = make_managed_position()

    (
        _,
        price_monitor,
        stop_monitor,
    ) = make_components(
        position
    )

    push_price(
        price_monitor,
        ltp=85,
    )

    stop_monitor.evaluate(
        position=position,
        evaluated_at=NOW,
    )

    assert stop_monitor.has_triggered(
        position.position_id
    ) is True

    stop_monitor.clear()

    assert stop_monitor.has_triggered(
        position.position_id
    ) is False


def test_negative_max_price_age_rejected() -> None:
    position = make_managed_position()

    registry = PositionRegistry()

    registry.register(
        position
    )

    price_monitor = (
        OptionPositionPriceMonitor(
            registry=registry
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "max_price_age cannot be negative"
        ),
    ):
        StopLossTriggerMonitor(
            price_monitor=price_monitor,
            max_price_age=timedelta(
                seconds=-1
            ),
        )