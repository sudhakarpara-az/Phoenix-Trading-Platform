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
from src.risk.filled_position_risk_initializer import (
    FilledPositionRiskInitializer,
)
from src.risk.option_position_price_monitor import (
    OptionPositionPriceMonitor,
    OptionPriceTick,
)
from src.risk.position_registry import (
    DuplicatePositionError,
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPositionState,
    PositionRiskId,
    StopLossState,
)
from src.risk.stop_loss_policy import (
    StopLossConfig,
    StopLossPolicy,
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

FILL_TIME = datetime(
    2026,
    8,
    7,
    14,
    30,
)

INIT_TIME = (
    FILL_TIME
    + timedelta(seconds=1)
)


def make_option(
    *,
    security_id: str = "41009",
    option_type: OptionType = OptionType.CALL,
    lot_size: int = 65,
) -> SelectedOption:
    side = (
        "CE"
        if option_type is OptionType.CALL
        else "PE"
    )

    delta = (
        0.64
        if option_type is OptionType.CALL
        else -0.64
    )

    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-"
                    f"24450-{side}"
                ),
                security_id=security_id,
                option_type=option_type,
                strike=24450,
                expiry=EXPIRY,
                lot_size=lot_size,
            ),
            quote=OptionQuote(
                ltp=100,
                bid=99.95,
                ask=100.05,
                volume=1000,
                open_interest=50000,
                received_at=FILL_TIME,
            ),
            greeks=OptionGreeks(
                delta=delta,
                calculated_at=FILL_TIME,
            ),
        ),
        selected_at=FILL_TIME,
        selection_delta_target=0.64,
    )


def make_filled_position(
    *,
    position_id: str = "POS-M07-T15",
    quantity: int = 65,
    entry_price: float = 100.65,
    option_type: OptionType = OptionType.CALL,
    security_id: str = "41009",
    level: EntryLevel = EntryLevel.K5,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            position_id
        ),
        signal_id=SignalId(
            f"SIG-{position_id}"
        ),
        entry_intent_id=OrderIntentId(
            f"ORD-{position_id}"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id=(
                    f"DHAN-{position_id}"
                ),
            )
        ),
        selected_option=make_option(
            security_id=security_id,
            option_type=option_type,
        ),
        level=level,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=FILL_TIME,
    )


def make_components(
    *,
    risk_points: float = 15.0,
):
    registry = PositionRegistry()

    stop_policy = StopLossPolicy(
        StopLossConfig(
            risk_points=risk_points,
            tick_size=0.05,
        )
    )

    initializer = (
        FilledPositionRiskInitializer(
            registry=registry,
            stop_loss_policy=stop_policy,
        )
    )

    return (
        registry,
        initializer,
    )


def test_m06_position_initializes_m07_position() -> None:
    registry, initializer = (
        make_components()
    )

    filled = make_filled_position()

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.position
        is filled
    )

    assert (
        managed.state
        is ManagedPositionState.OPEN
    )

    assert managed.open_quantity == 65
    assert managed.closed_quantity == 0
    assert managed.realized_pnl == 0

    assert registry.count() == 1


def test_default_risk_id_derived_from_position_id() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position(
        position_id="POS-ABC"
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.risk_id.value
        == "RISK:POS-ABC"
    )


def test_explicit_risk_id_supported() -> None:
    _, initializer = (
        make_components()
    )

    managed = initializer.initialize(
        position=make_filled_position(),
        initialized_at=INIT_TIME,
        risk_id=PositionRiskId(
            "CUSTOM-RISK-001"
        ),
    )

    assert (
        managed.risk_id.value
        == "CUSTOM-RISK-001"
    )


def test_actual_m06_fill_price_is_preserved() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position(
        entry_price=100.65
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.entry_price
        == 100.65
    )

    assert (
        managed.entry_price
        == filled.entry_price
    )


def test_stop_uses_actual_m06_fill_price() -> None:
    _, initializer = (
        make_components(
            risk_points=15
        )
    )

    filled = make_filled_position(
        entry_price=100.65
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert managed.stop_loss is not None

    assert (
        managed.stop_loss.stop_price
        == 85.65
    )

    assert (
        managed.stop_loss.risk_points
        == pytest.approx(15)
    )

    assert (
        managed.stop_loss.state
        is StopLossState.ARMED
    )


def test_stop_does_not_use_old_option_quote() -> None:
    """
    Option quote inside SelectedOption is 100.

    Actual M06 fill is 100.65.

    Correct stop:
        100.65 - 15 = 85.65

    Incorrect quote-based stop would be:
        100 - 15 = 85
    """

    _, initializer = (
        make_components()
    )

    filled = make_filled_position(
        entry_price=100.65
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert managed.stop_loss is not None

    assert (
        managed.stop_loss.stop_price
        == 85.65
    )

    assert (
        managed.stop_loss.stop_price
        != 85.0
    )


def test_full_filled_quantity_becomes_open_quantity() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position(
        quantity=130
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert managed.original_quantity == 130
    assert managed.open_quantity == 130
    assert managed.closed_quantity == 0


def test_initial_target_is_not_invented() -> None:
    """
    T15 must not fabricate an option target from a NIFTY
    strategy level.

    T09 / later target integration owns that boundary.
    """

    _, initializer = (
        make_components()
    )

    managed = initializer.initialize(
        position=make_filled_position(),
        initialized_at=INIT_TIME,
    )

    assert managed.target is None


def test_level_is_preserved_from_m06() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position(
        level=EntryLevel.K7
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.position.level
        is EntryLevel.K7
    )


def test_security_id_is_preserved() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position(
        security_id="41019"
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.security_id
        == "41019"
    )


def test_call_contract_preserved() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position(
        option_type=OptionType.CALL
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.position.option_type
        is OptionType.CALL
    )


def test_put_contract_preserved() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position(
        option_type=OptionType.PUT,
        security_id="41019",
    )

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.position.option_type
        is OptionType.PUT
    )


def test_broker_reference_is_preserved() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position()

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.position
        .entry_broker_reference
        == filled.entry_broker_reference
    )


def test_signal_identity_is_preserved() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position()

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.position.signal_id
        == filled.signal_id
    )


def test_entry_intent_identity_is_preserved() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position()

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    assert (
        managed.position.entry_intent_id
        == filled.entry_intent_id
    )


def test_initializer_registers_position() -> None:
    registry, initializer = (
        make_components()
    )

    filled = make_filled_position()

    managed = initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    stored = registry.require(
        filled.position_id
    )

    assert stored is managed


def test_same_m06_position_cannot_be_initialized_twice() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position()

    initializer.initialize(
        position=filled,
        initialized_at=INIT_TIME,
    )

    with pytest.raises(
        DuplicatePositionError,
        match=(
            "managed position already registered"
        ),
    ):
        initializer.initialize(
            position=filled,
            initialized_at=(
                INIT_TIME
                + timedelta(seconds=1)
            ),
        )


def test_initialization_before_fill_time_rejected() -> None:
    _, initializer = (
        make_components()
    )

    filled = make_filled_position()

    with pytest.raises(
        ValueError,
        match=(
            "initialized_at cannot be before "
            "position filled_at"
        ),
    ):
        initializer.initialize(
            position=filled,
            initialized_at=(
                FILL_TIME
                - timedelta(seconds=1)
            ),
        )


def test_initialization_at_fill_time_allowed() -> None:
    _, initializer = (
        make_components()
    )

    managed = initializer.initialize(
        position=make_filled_position(),
        initialized_at=FILL_TIME,
    )

    assert managed.created_at == FILL_TIME

    assert managed.updated_at == FILL_TIME


def test_price_monitor_tracks_initialized_position() -> None:
    registry, initializer = (
        make_components()
    )

    managed = initializer.initialize(
        position=make_filled_position(),
        initialized_at=INIT_TIME,
    )

    monitor = OptionPositionPriceMonitor(
        registry=registry
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id=managed.security_id,
            ltp=112,
            received_at=(
                INIT_TIME
                + timedelta(seconds=1)
            ),
        )
    )

    assert result.accepted is True

    latest = monitor.get_for_position(
        managed.position_id
    )

    assert latest is not None
    assert latest.ltp == 112


def test_initialized_position_blocks_open_level() -> None:
    registry, initializer = (
        make_components()
    )

    initializer.initialize(
        position=make_filled_position(
            level=EntryLevel.K5
        ),
        initialized_at=INIT_TIME,
    )

    assert (
        registry.has_open_position_for_level(
            level=EntryLevel.K5
        )
        is True
    )


def test_different_level_remains_unblocked() -> None:
    registry, initializer = (
        make_components()
    )

    initializer.initialize(
        position=make_filled_position(
            level=EntryLevel.K5
        ),
        initialized_at=INIT_TIME,
    )

    assert (
        registry.has_open_position_for_level(
            level=EntryLevel.K7
        )
        is False
    )


def test_initialized_position_is_exposed_as_open() -> None:
    registry, initializer = (
        make_components()
    )

    managed = initializer.initialize(
        position=make_filled_position(),
        initialized_at=INIT_TIME,
    )

    assert (
        registry.open_positions()
        == (managed,)
    )


def test_custom_stop_risk_flows_into_managed_position() -> None:
    _, initializer = (
        make_components(
            risk_points=12
        )
    )

    managed = initializer.initialize(
        position=make_filled_position(
            entry_price=100.65
        ),
        initialized_at=INIT_TIME,
    )

    assert managed.stop_loss is not None

    assert (
        managed.stop_loss.stop_price
        == 88.65
    )

    assert (
        managed.stop_loss.risk_points
        == pytest.approx(12)
    )