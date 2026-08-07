from dataclasses import replace
from datetime import date, datetime, timedelta

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
from src.risk.position_registry import (
    DuplicatePositionError,
    DuplicateRiskIdError,
    PositionNotFoundError,
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
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


def make_option(
    *,
    security_id: str = "41009",
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    "NIFTY50-20260811-24450-CE"
                ),
                security_id=security_id,
                option_type=OptionType.CALL,
                strike=24450.0,
                expiry=EXPIRY,
                lot_size=65,
            ),
            quote=OptionQuote(
                ltp=100.0,
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
    position_id: str = "POS-001",
    signal_id: str = "SIG-001",
    intent_id: str = "ORD-001",
    level: EntryLevel = EntryLevel.K5,
    quantity: int = 65,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            position_id
        ),
        signal_id=SignalId(
            signal_id
        ),
        entry_intent_id=OrderIntentId(
            intent_id
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id=(
                    f"DHAN-{position_id}"
                ),
            )
        ),
        selected_option=make_option(),
        level=level,
        quantity=quantity,
        entry_price=100.65,
        filled_at=NOW,
    )


def make_managed_position(
    *,
    position_id: str = "POS-001",
    risk_id: str = "RISK-001",
    signal_id: str = "SIG-001",
    intent_id: str = "ORD-001",
    level: EntryLevel = EntryLevel.K5,
    quantity: int = 65,
    open_quantity: int | None = None,
    closed_quantity: int = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
    realized_pnl: float = 0.0,
    updated_at: datetime = NOW,
) -> ManagedPosition:
    position = make_filled_position(
        position_id=position_id,
        signal_id=signal_id,
        intent_id=intent_id,
        level=level,
        quantity=quantity,
    )

    actual_open_quantity = (
        quantity - closed_quantity
        if open_quantity is None
        else open_quantity
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            risk_id
        ),
        position=position,
        open_quantity=actual_open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=realized_pnl,
        state=state,
        stop_loss=None,
        target=None,
        created_at=NOW,
        updated_at=updated_at,
    )


def test_register_position() -> None:
    registry = PositionRegistry()

    position = make_managed_position()

    result = registry.register(
        position
    )

    assert result is position

    assert registry.count() == 1

    assert registry.contains(
        position.position_id
    ) is True


def test_get_position_by_position_id() -> None:
    registry = PositionRegistry()

    position = make_managed_position()

    registry.register(
        position
    )

    result = registry.get(
        position.position_id
    )

    assert result is position


def test_get_unknown_position_returns_none() -> None:
    registry = PositionRegistry()

    result = registry.get(
        FilledPositionId(
            "POS-UNKNOWN"
        )
    )

    assert result is None


def test_require_unknown_position_raises() -> None:
    registry = PositionRegistry()

    with pytest.raises(
        PositionNotFoundError,
        match=(
            "managed position not found"
        ),
    ):
        registry.require(
            FilledPositionId(
                "POS-UNKNOWN"
            )
        )


def test_get_by_risk_id() -> None:
    registry = PositionRegistry()

    position = make_managed_position(
        risk_id="RISK-ABC"
    )

    registry.register(
        position
    )

    result = registry.get_by_risk_id(
        PositionRiskId(
            "RISK-ABC"
        )
    )

    assert result is position


def test_unknown_risk_id_returns_none() -> None:
    registry = PositionRegistry()

    result = registry.get_by_risk_id(
        PositionRiskId(
            "RISK-UNKNOWN"
        )
    )

    assert result is None


def test_duplicate_position_registration_rejected() -> None:
    registry = PositionRegistry()

    first = make_managed_position(
        position_id="POS-001",
        risk_id="RISK-001",
    )

    duplicate = make_managed_position(
        position_id="POS-001",
        risk_id="RISK-002",
    )

    registry.register(
        first
    )

    with pytest.raises(
        DuplicatePositionError,
        match=(
            "managed position already registered"
        ),
    ):
        registry.register(
            duplicate
        )


def test_duplicate_risk_id_rejected() -> None:
    registry = PositionRegistry()

    first = make_managed_position(
        position_id="POS-001",
        risk_id="RISK-SAME",
    )

    second = make_managed_position(
        position_id="POS-002",
        risk_id="RISK-SAME",
        signal_id="SIG-002",
        intent_id="ORD-002",
    )

    registry.register(
        first
    )

    with pytest.raises(
        DuplicateRiskIdError,
        match=(
            "position risk id already registered"
        ),
    ):
        registry.register(
            second
        )


def test_replace_existing_snapshot() -> None:
    registry = PositionRegistry()

    original = make_managed_position()

    registry.register(
        original
    )

    updated = replace(
        original,
        open_quantity=35,
        closed_quantity=30,
        realized_pnl=780,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
        updated_at=(
            NOW
            + timedelta(minutes=1)
        ),
    )

    result = registry.replace(
        updated
    )

    assert result is updated

    stored = registry.require(
        original.position_id
    )

    assert stored.open_quantity == 35
    assert stored.closed_quantity == 30
    assert stored.realized_pnl == 780

    assert (
        stored.state
        is ManagedPositionState.PARTIALLY_EXITED
    )


def test_replace_unknown_position_rejected() -> None:
    registry = PositionRegistry()

    position = make_managed_position()

    with pytest.raises(
        PositionNotFoundError,
        match=(
            "managed position not found"
        ),
    ):
        registry.replace(
            position
        )


def test_replace_cannot_change_risk_id() -> None:
    registry = PositionRegistry()

    original = make_managed_position(
        risk_id="RISK-001"
    )

    registry.register(
        original
    )

    changed = replace(
        original,
        risk_id=PositionRiskId(
            "RISK-OTHER"
        ),
        updated_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    with pytest.raises(
        ValueError,
        match=(
            "position risk id cannot change "
            "during replacement"
        ),
    ):
        registry.replace(
            changed
        )


def test_replace_rejects_older_snapshot() -> None:
    registry = PositionRegistry()

    original = make_managed_position(
        updated_at=(
            NOW
            + timedelta(minutes=1)
        )
    )

    registry.register(
        original
    )

    older = replace(
        original,
        updated_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "replacement snapshot cannot be older "
            "than current snapshot"
        ),
    ):
        registry.replace(
            older
        )


def test_all_returns_tuple() -> None:
    registry = PositionRegistry()

    registry.register(
        make_managed_position(
            position_id="POS-001",
            risk_id="RISK-001",
        )
    )

    registry.register(
        make_managed_position(
            position_id="POS-002",
            risk_id="RISK-002",
            signal_id="SIG-002",
            intent_id="ORD-002",
        )
    )

    result = registry.all()

    assert isinstance(
        result,
        tuple,
    )

    assert len(result) == 2


def test_by_state() -> None:
    registry = PositionRegistry()

    open_position = (
        make_managed_position(
            position_id="POS-001",
            risk_id="RISK-001",
            state=ManagedPositionState.OPEN,
        )
    )

    closed_position = (
        make_managed_position(
            position_id="POS-002",
            risk_id="RISK-002",
            signal_id="SIG-002",
            intent_id="ORD-002",
            open_quantity=0,
            closed_quantity=65,
            state=ManagedPositionState.CLOSED,
        )
    )

    registry.register(
        open_position
    )

    registry.register(
        closed_position
    )

    result = registry.by_state(
        ManagedPositionState.CLOSED
    )

    assert result == (
        closed_position,
    )


def test_open_positions_include_open() -> None:
    registry = PositionRegistry()

    position = make_managed_position()

    registry.register(
        position
    )

    assert (
        registry.open_positions()
        == (position,)
    )


def test_open_positions_include_partial() -> None:
    registry = PositionRegistry()

    position = make_managed_position(
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    registry.register(
        position
    )

    assert (
        registry.open_positions()
        == (position,)
    )


def test_open_positions_include_exit_pending() -> None:
    registry = PositionRegistry()

    position = make_managed_position(
        state=(
            ManagedPositionState
            .EXIT_PENDING
        ),
    )

    registry.register(
        position
    )

    assert (
        registry.open_positions()
        == (position,)
    )


def test_closed_positions_excluded_from_open() -> None:
    registry = PositionRegistry()

    position = make_managed_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    registry.register(
        position
    )

    assert (
        registry.open_positions()
        == ()
    )

    assert (
        registry.closed_positions()
        == (position,)
    )


def test_open_position_for_k5_detected() -> None:
    registry = PositionRegistry()

    registry.register(
        make_managed_position(
            level=EntryLevel.K5,
        )
    )

    assert registry.has_open_position_for_level(
        level=EntryLevel.K5
    ) is True


def test_closed_k5_does_not_block_level() -> None:
    registry = PositionRegistry()

    registry.register(
        make_managed_position(
            level=EntryLevel.K5,
            open_quantity=0,
            closed_quantity=65,
            state=ManagedPositionState.CLOSED,
        )
    )

    assert registry.has_open_position_for_level(
        level=EntryLevel.K5
    ) is False


def test_open_k5_does_not_block_k7() -> None:
    registry = PositionRegistry()

    registry.register(
        make_managed_position(
            level=EntryLevel.K5,
        )
    )

    assert registry.has_open_position_for_level(
        level=EntryLevel.K7
    ) is False


def test_clear_registry() -> None:
    registry = PositionRegistry()

    position = make_managed_position()

    registry.register(
        position
    )

    assert registry.count() == 1

    registry.clear()

    assert registry.count() == 0
    assert registry.all() == ()

    assert registry.get(
        position.position_id
    ) is None

    assert registry.get_by_risk_id(
        position.risk_id
    ) is None