from datetime import (
    date,
    datetime,
    timedelta,
)

import math
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
from src.risk.daily_risk_manager import (
    DailyRiskManager,
)
from src.risk.position_pnl_tracker import (
    PositionPnLTracker,
)
from src.risk.position_registry import (
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

TRADING_DATE = date(
    2026,
    8,
    7,
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


def make_managed_position(
    *,
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    entry_price: float = 100,
    realized_pnl: float = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    filled = FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T18"
        ),
        signal_id=SignalId(
            "SIG-M07-T18"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T18"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="ENTRY-M07-T18",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            "RISK-M07-T18"
        ),
        position=filled,
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=realized_pnl,
        state=state,
        stop_loss=None,
        target=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_register_open_position() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    state = tracker.register(
        position=position,
        registered_at=NOW,
    )

    assert state.entry_price == 100
    assert state.original_quantity == 65
    assert state.open_quantity == 65
    assert state.closed_quantity == 0

    assert state.realized_pnl == 0
    assert state.unrealized_pnl == 0
    assert state.total_pnl == 0

    assert state.latest_ltp is None


def test_register_uses_actual_entry_price() -> None:
    tracker = PositionPnLTracker()

    state = tracker.register(
        position=make_managed_position(
            entry_price=100.65
        ),
        registered_at=NOW,
    )

    assert state.entry_price == 100.65


def test_duplicate_registration_rejected() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "position already registered for "
            "P&L tracking"
        ),
    ):
        tracker.register(
            position=position,
            registered_at=NOW,
        )


def test_mark_to_market_profit() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    state = tracker.mark_to_market(
        position_id=position.position_id,
        ltp=112,
        marked_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert state.unrealized_points == 12
    assert state.unrealized_pnl == 780
    assert state.realized_pnl == 0
    assert state.total_pnl == 780


def test_mark_to_market_loss() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    state = tracker.mark_to_market(
        position_id=position.position_id,
        ltp=90,
        marked_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert state.unrealized_points == -10
    assert state.unrealized_pnl == -650
    assert state.total_pnl == -650


def test_partial_exit_realized_profit() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    state = tracker.record_exit_fill(
        position_id=position.position_id,
        quantity=30,
        price=126,
        filled_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert state.open_quantity == 35
    assert state.closed_quantity == 30

    assert state.realized_pnl == 780
    assert state.unrealized_pnl == 0
    assert state.total_pnl == 780


def test_partial_exit_recalculates_existing_mark() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    tracker.mark_to_market(
        position_id=position.position_id,
        ltp=112,
        marked_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    state = tracker.record_exit_fill(
        position_id=position.position_id,
        quantity=30,
        price=126,
        filled_at=(
            NOW
            + timedelta(seconds=2)
        ),
    )

    assert state.realized_pnl == 780

    # Remaining:
    # (112 - 100) * 35
    assert state.unrealized_pnl == 420

    assert state.total_pnl == 1200


def test_multiple_exit_fills_accumulate() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    tracker.record_exit_fill(
        position_id=position.position_id,
        quantity=20,
        price=120,
        filled_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    state = tracker.record_exit_fill(
        position_id=position.position_id,
        quantity=10,
        price=130,
        filled_at=(
            NOW
            + timedelta(seconds=2)
        ),
    )

    assert state.closed_quantity == 30
    assert state.open_quantity == 35

    assert state.realized_pnl == 700

    assert len(
        state.exit_fills
    ) == 2


def test_full_exit_zeroes_unrealized_exposure() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    tracker.mark_to_market(
        position_id=position.position_id,
        ltp=150,
        marked_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    state = tracker.record_exit_fill(
        position_id=position.position_id,
        quantity=65,
        price=126,
        filled_at=(
            NOW
            + timedelta(seconds=2)
        ),
    )

    assert state.open_quantity == 0
    assert state.closed_quantity == 65
    assert state.is_closed is True

    assert state.realized_pnl == 1690
    assert state.unrealized_pnl == 0
    assert state.total_pnl == 1690


def test_mark_after_close_keeps_unrealized_zero() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    tracker.record_exit_fill(
        position_id=position.position_id,
        quantity=65,
        price=126,
        filled_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    state = tracker.mark_to_market(
        position_id=position.position_id,
        ltp=200,
        marked_at=(
            NOW
            + timedelta(seconds=2)
        ),
    )

    assert state.open_quantity == 0
    assert state.unrealized_pnl == 0
    assert state.total_pnl == 1690


def test_exit_fill_cannot_exceed_open_quantity() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit fill quantity cannot exceed "
            "tracked open quantity"
        ),
    ):
        tracker.record_exit_fill(
            position_id=position.position_id,
            quantity=66,
            price=126,
            filled_at=(
                NOW
                + timedelta(seconds=1)
            ),
        )


def test_zero_fill_quantity_rejected() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit fill quantity must be "
            "greater than zero"
        ),
    ):
        tracker.record_exit_fill(
            position_id=position.position_id,
            quantity=0,
            price=126,
            filled_at=NOW,
        )


def test_zero_fill_price_rejected() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "exit fill price must be "
            "greater than zero"
        ),
    ):
        tracker.record_exit_fill(
            position_id=position.position_id,
            quantity=30,
            price=0,
            filled_at=NOW,
        )


def test_nan_fill_price_rejected() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="exit fill price must be finite",
    ):
        tracker.record_exit_fill(
            position_id=position.position_id,
            quantity=30,
            price=math.nan,
            filled_at=NOW,
        )


def test_zero_ltp_rejected() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match=(
            "ltp must be greater than zero"
        ),
    ):
        tracker.mark_to_market(
            position_id=position.position_id,
            ltp=0,
            marked_at=(
                NOW
                + timedelta(seconds=1)
            ),
        )


def test_nan_ltp_rejected() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="ltp must be finite",
    ):
        tracker.mark_to_market(
            position_id=position.position_id,
            ltp=math.nan,
            marked_at=(
                NOW
                + timedelta(seconds=1)
            ),
        )


def test_stale_mark_rejected() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    first_mark = (
        NOW
        + timedelta(seconds=2)
    )

    tracker.mark_to_market(
        position_id=position.position_id,
        ltp=112,
        marked_at=first_mark,
    )

    with pytest.raises(
        ValueError,
        match=(
            "mark timestamp must be newer than "
            "latest mark"
        ),
    ):
        tracker.mark_to_market(
            position_id=position.position_id,
            ltp=90,
            marked_at=(
                NOW
                + timedelta(seconds=1)
            ),
        )


def test_equal_mark_timestamp_rejected() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    marked_at = (
        NOW
        + timedelta(seconds=1)
    )

    tracker.mark_to_market(
        position_id=position.position_id,
        ltp=112,
        marked_at=marked_at,
    )

    with pytest.raises(
        ValueError,
        match=(
            "mark timestamp must be newer than "
            "latest mark"
        ),
    ):
        tracker.mark_to_market(
            position_id=position.position_id,
            ltp=113,
            marked_at=marked_at,
        )


def test_tracker_exports_position_pnl() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    tracker.mark_to_market(
        position_id=position.position_id,
        ltp=112,
        marked_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    pnl = tracker.to_position_pnl(
        position.position_id
    )

    assert pnl.realized_pnl == 0
    assert pnl.unrealized_pnl == 780
    assert pnl.total_pnl == 780
    assert pnl.unrealized_points == 12


def test_tracker_pnl_map_supports_daily_risk_manager() -> None:
    position = make_managed_position()

    registry = PositionRegistry()

    registry.register(
        position
    )

    tracker = PositionPnLTracker()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    tracker.mark_to_market(
        position_id=position.position_id,
        ltp=112,
        marked_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    manager = DailyRiskManager(
        registry=registry
    )

    daily = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls=(
            tracker.pnl_map()
        ),
        captured_at=(
            NOW
            + timedelta(seconds=1)
        ),
    )

    assert daily.unrealized_pnl == 780
    assert daily.total_pnl == 780


def test_partial_existing_position_can_be_registered() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position(
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        realized_pnl=780,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    state = tracker.register(
        position=position,
        registered_at=NOW,
    )

    assert state.open_quantity == 35
    assert state.closed_quantity == 30
    assert state.realized_pnl == 780
    assert state.total_pnl == 780


def test_unknown_position_rejected() -> None:
    tracker = PositionPnLTracker()

    with pytest.raises(
        KeyError,
        match=(
            "position is not registered for "
            "P&L tracking"
        ),
    ):
        tracker.require(
            FilledPositionId(
                "UNKNOWN"
            )
        )


def test_clear_tracker() -> None:
    tracker = PositionPnLTracker()

    position = make_managed_position()

    tracker.register(
        position=position,
        registered_at=NOW,
    )

    assert len(
        tracker.all_states()
    ) == 1

    tracker.clear()

    assert tracker.all_states() == ()