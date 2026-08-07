from dataclasses import replace
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
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.reentry_risk_synchronizer import (
    ReentryRiskSynchronizer,
    ReentrySyncStatus,
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

LATER = (
    NOW
    + timedelta(minutes=1)
)


class FakeReentryPort:
    def __init__(self) -> None:
        self.open_calls = []
        self.closed_calls = []

    def mark_position_open(
        self,
        *,
        level,
        position_id,
        changed_at,
    ) -> None:
        self.open_calls.append(
            (
                level,
                position_id,
                changed_at,
            )
        )

    def mark_position_closed(
        self,
        *,
        level,
        position_id,
        changed_at,
    ) -> None:
        self.closed_calls.append(
            (
                level,
                position_id,
                changed_at,
            )
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


def make_position(
    *,
    level: EntryLevel = EntryLevel.K5,
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    filled = FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T19"
        ),
        signal_id=SignalId(
            "SIG-M07-T19"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T19"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-M07-T19",
            )
        ),
        selected_option=make_option(),
        level=level,
        quantity=quantity,
        entry_price=100,
        filled_at=NOW,
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-T19"
        ),
        position=filled,
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
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

    port = FakeReentryPort()

    synchronizer = (
        ReentryRiskSynchronizer(
            registry=registry,
            reentry_port=port,
        )
    )

    return (
        registry,
        port,
        synchronizer,
    )


def test_open_position_syncs_to_reentry_port() -> None:
    position = make_position()

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    result = synchronizer.sync_position_open(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        result.status
        is ReentrySyncStatus
        .OPEN_POSITION_SYNCED
    )

    assert result.reentry_released is False

    assert len(
        port.open_calls
    ) == 1

    assert (
        port.open_calls[0][0]
        is EntryLevel.K5
    )


def test_open_sync_is_idempotent() -> None:
    position = make_position()

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    first = synchronizer.sync_position_open(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    second = synchronizer.sync_position_open(
        position_id=position.position_id,
        synchronized_at=LATER,
    )

    assert (
        first.status
        is ReentrySyncStatus
        .OPEN_POSITION_SYNCED
    )

    assert (
        second.status
        is ReentrySyncStatus.ALREADY_SYNCED
    )

    assert len(
        port.open_calls
    ) == 1


def test_exit_pending_does_not_release_reentry() -> None:
    position = make_position(
        state=ManagedPositionState.EXIT_PENDING
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        result.status
        is ReentrySyncStatus.STILL_OPEN
    )

    assert result.reentry_released is False

    assert port.closed_calls == []


def test_partial_exit_does_not_release_reentry() -> None:
    position = make_position(
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        result.status
        is ReentrySyncStatus.STILL_OPEN
    )

    assert result.open_quantity == 35

    assert port.closed_calls == []


def test_reconciliation_required_does_not_release_reentry() -> None:
    position = make_position(
        state=(
            ManagedPositionState
            .RECONCILIATION_REQUIRED
        )
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        result.status
        is ReentrySyncStatus.STILL_OPEN
    )

    assert port.closed_calls == []


def test_closed_position_releases_reentry() -> None:
    position = make_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        result.status
        is ReentrySyncStatus
        .CLOSED_POSITION_SYNCED
    )

    assert result.reentry_released is True

    assert len(
        port.closed_calls
    ) == 1


def test_closed_sync_preserves_level() -> None:
    position = make_position(
        level=EntryLevel.K7,
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        port.closed_calls[0][0]
        is EntryLevel.K7
    )


def test_closed_sync_preserves_position_id() -> None:
    position = make_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        port.closed_calls[0][1]
        == position.position_id
    )


def test_closed_sync_is_idempotent() -> None:
    position = make_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    first = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    second = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=LATER,
    )

    assert (
        first.status
        is ReentrySyncStatus
        .CLOSED_POSITION_SYNCED
    )

    assert (
        second.status
        is ReentrySyncStatus.ALREADY_SYNCED
    )

    assert len(
        port.closed_calls
    ) == 1


def test_open_quantity_must_be_zero_before_release() -> None:
    """
    CLOSED with open quantity is already prohibited by
    ManagedPosition validation.

    This test verifies the normal non-closed state remains
    unreleased while quantity exists.
    """

    position = make_position(
        open_quantity=1,
        closed_quantity=64,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert result.reentry_released is False
    assert port.closed_calls == []


def test_sell_submission_alone_does_not_release_reentry() -> None:
    position = make_position(
        state=ManagedPositionState.EXIT_PENDING
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert (
        result.status
        is ReentrySyncStatus.STILL_OPEN
    )

    assert port.closed_calls == []


def test_reentry_released_after_final_fill_updates_registry() -> None:
    position = make_position()

    (
        registry,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    # Simulate final broker fill/lifecycle update.
    closed = replace(
        position,
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
        updated_at=LATER,
    )

    registry.replace(
        closed
    )

    result = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=LATER,
    )

    assert result.reentry_released is True

    assert len(
        port.closed_calls
    ) == 1


def test_partial_fill_then_final_fill_releases_only_after_final() -> None:
    position = make_position()

    (
        registry,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    partial = replace(
        position,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
        updated_at=LATER,
    )

    registry.replace(
        partial
    )

    first = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=LATER,
    )

    assert (
        first.status
        is ReentrySyncStatus.STILL_OPEN
    )

    assert port.closed_calls == []

    final_time = (
        LATER
        + timedelta(seconds=1)
    )

    closed = replace(
        partial,
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
        updated_at=final_time,
    )

    registry.replace(
        closed
    )

    second = synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=final_time,
    )

    assert (
        second.status
        is ReentrySyncStatus
        .CLOSED_POSITION_SYNCED
    )

    assert len(
        port.closed_calls
    ) == 1


def test_unknown_position_raises_registry_error() -> None:
    registry = PositionRegistry()
    port = FakeReentryPort()

    synchronizer = (
        ReentryRiskSynchronizer(
            registry=registry,
            reentry_port=port,
        )
    )

    with pytest.raises(KeyError):
        synchronizer.sync_position_state(
            position_id=FilledPositionId(
                "UNKNOWN"
            ),
            synchronized_at=NOW,
        )


def test_clear_removes_sync_memory() -> None:
    position = make_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    (
        _,
        port,
        synchronizer,
    ) = make_components(
        position
    )

    synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=NOW,
    )

    assert synchronizer.is_closed_synced(
        position.position_id
    ) is True

    synchronizer.clear()

    assert synchronizer.is_closed_synced(
        position.position_id
    ) is False

    synchronizer.sync_position_state(
        position_id=position.position_id,
        synchronized_at=LATER,
    )

    assert len(
        port.closed_calls
    ) == 2