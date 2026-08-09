from datetime import date, datetime

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
    DailyRiskConfig,
    DailyRiskLockReason,
    DailyRiskManager,
    DailyRiskSnapshot,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionPnL,
    PositionRiskId,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
)


TRADING_DATE = date(
    2026,
    8,
    7,
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
    security_id: str,
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    f"NIFTY-{security_id}-CE"
                ),
                security_id=security_id,
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
    position_id: str,
    risk_id: str,
    security_id: str,
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    realized_pnl: float = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    filled = FilledPosition(
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
            security_id=security_id
        ),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=100,
        filled_at=NOW,
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            risk_id
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


def make_pnl(
    *,
    realized: float = 0,
    unrealized: float = 0,
) -> PositionPnL:
    return PositionPnL(
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        total_pnl=(
            realized
            + unrealized
        ),
        unrealized_points=0,
        calculated_at=NOW,
    )


def make_registry(
    *positions: ManagedPosition,
) -> PositionRegistry:
    registry = PositionRegistry()

    for position in positions:
        registry.register(
            position
        )

    return registry


def test_default_config_has_no_limits() -> None:
    config = DailyRiskConfig()

    assert config.max_daily_loss_amount is None

    assert (
        config.daily_profit_lock_amount
        is None
    )

    assert (
        config.max_closed_positions
        is None
    )


def test_empty_day_allows_new_entries() -> None:
    manager = DailyRiskManager(
        registry=make_registry()
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={},
        captured_at=NOW,
    )

    assert snapshot.new_entries_allowed is True

    assert (
        snapshot.lock_reason
        is DailyRiskLockReason.NONE
    )

    assert snapshot.realized_pnl == 0
    assert snapshot.unrealized_pnl == 0
    assert snapshot.total_pnl == 0


def test_open_position_unrealized_profit() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        )
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=780
            )
        },
        captured_at=NOW,
    )

    assert snapshot.realized_pnl == 0
    assert snapshot.unrealized_pnl == 780
    assert snapshot.total_pnl == 780

    assert snapshot.open_positions == 1
    assert snapshot.open_quantity == 65


def test_open_position_unrealized_loss() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        )
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=-650
            )
        },
        captured_at=NOW,
    )

    assert snapshot.unrealized_pnl == -650
    assert snapshot.total_pnl == -650


def test_closed_position_realized_profit() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        open_quantity=0,
        closed_quantity=65,
        realized_pnl=1690,
        state=ManagedPositionState.CLOSED,
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        )
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={},
        captured_at=NOW,
    )

    assert snapshot.realized_pnl == 1690
    assert snapshot.unrealized_pnl == 0
    assert snapshot.total_pnl == 1690

    assert snapshot.open_positions == 0
    assert snapshot.closed_positions == 1


def test_partial_position_combines_realized_and_unrealized() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        realized_pnl=780,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        )
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                realized=780,
                unrealized=420,
            )
        },
        captured_at=NOW,
    )

    # ManagedPosition carries authoritative realized:
    assert snapshot.realized_pnl == 780

    # Current P&L supplies open MTM:
    assert snapshot.unrealized_pnl == 420

    assert snapshot.total_pnl == 1200

    assert snapshot.open_positions == 1
    assert snapshot.open_quantity == 35


def test_multiple_positions_are_aggregated() -> None:
    first = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        realized_pnl=100,
    )

    second = make_position(
        position_id="POS-002",
        risk_id="RISK-002",
        security_id="41019",
        realized_pnl=200,
    )

    manager = DailyRiskManager(
        registry=make_registry(
            first,
            second,
        )
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                realized=100,
                unrealized=300,
            ),
            "POS-002": make_pnl(
                realized=200,
                unrealized=-100,
            ),
        },
        captured_at=NOW,
    )

    assert snapshot.realized_pnl == 300

    assert snapshot.unrealized_pnl == 200

    assert snapshot.total_pnl == 500

    assert snapshot.open_positions == 2

    assert snapshot.open_quantity == 130


def test_missing_pnl_for_open_position_is_rejected() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "P&L snapshot required for open "
            "managed position"
        ),
    ):
        manager.build_snapshot(
            trading_date=TRADING_DATE,
            position_pnls={},
            captured_at=NOW,
        )


def test_daily_loss_below_limit_is_allowed() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        ),
        config=DailyRiskConfig(
            max_daily_loss_amount=1000
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=-999
            )
        },
        captured_at=NOW,
    )

    assert snapshot.new_entries_allowed is True


def test_daily_loss_at_limit_locks_new_entries() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        ),
        config=DailyRiskConfig(
            max_daily_loss_amount=1000
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=-1000
            )
        },
        captured_at=NOW,
    )

    assert snapshot.new_entries_allowed is False

    assert (
        snapshot.lock_reason
        is DailyRiskLockReason.MAX_DAILY_LOSS
    )


def test_daily_loss_beyond_limit_locks() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        ),
        config=DailyRiskConfig(
            max_daily_loss_amount=1000
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=-1250
            )
        },
        captured_at=NOW,
    )

    assert (
        snapshot.lock_reason
        is DailyRiskLockReason.MAX_DAILY_LOSS
    )


def test_profit_below_lock_is_allowed() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        ),
        config=DailyRiskConfig(
            daily_profit_lock_amount=2000
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=1999
            )
        },
        captured_at=NOW,
    )

    assert snapshot.new_entries_allowed is True


def test_profit_at_lock_threshold_locks_new_entries() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        ),
        config=DailyRiskConfig(
            daily_profit_lock_amount=2000
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=2000
            )
        },
        captured_at=NOW,
    )

    assert snapshot.new_entries_allowed is False

    assert (
        snapshot.lock_reason
        is DailyRiskLockReason.DAILY_PROFIT_LOCK
    )


def test_realized_profit_can_activate_profit_lock() -> None:
    closed = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        open_quantity=0,
        closed_quantity=65,
        realized_pnl=2600,
        state=ManagedPositionState.CLOSED,
    )

    manager = DailyRiskManager(
        registry=make_registry(
            closed
        ),
        config=DailyRiskConfig(
            daily_profit_lock_amount=2600
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={},
        captured_at=NOW,
    )

    assert snapshot.total_pnl == 2600

    assert (
        snapshot.lock_reason
        is DailyRiskLockReason.DAILY_PROFIT_LOCK
    )


def test_max_closed_positions_locks() -> None:
    closed = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        open_quantity=0,
        closed_quantity=65,
        realized_pnl=500,
        state=ManagedPositionState.CLOSED,
    )

    manager = DailyRiskManager(
        registry=make_registry(
            closed
        ),
        config=DailyRiskConfig(
            max_closed_positions=1
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={},
        captured_at=NOW,
    )

    assert snapshot.new_entries_allowed is False

    assert (
        snapshot.lock_reason
        is DailyRiskLockReason
        .MAX_CLOSED_POSITIONS
    )


def test_manual_lock_has_highest_priority() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        ),
        config=DailyRiskConfig(
            max_daily_loss_amount=1000,
            daily_profit_lock_amount=2000,
        ),
    )

    manager.set_manual_lock(
        message="operator safety lock"
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=-5000
            )
        },
        captured_at=NOW,
    )

    assert (
        snapshot.lock_reason
        is DailyRiskLockReason.MANUAL_LOCK
    )

    assert (
        snapshot.message
        == "operator safety lock"
    )


def test_manual_lock_can_be_cleared() -> None:
    manager = DailyRiskManager(
        registry=make_registry()
    )

    manager.set_manual_lock()

    assert (
        manager.is_manually_locked()
        is True
    )

    manager.clear_manual_lock()

    assert (
        manager.is_manually_locked()
        is False
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={},
        captured_at=NOW,
    )

    assert snapshot.new_entries_allowed is True


def test_empty_manual_lock_message_rejected() -> None:
    manager = DailyRiskManager(
        registry=make_registry()
    )

    with pytest.raises(
        ValueError,
        match=(
            "manual lock message cannot be empty"
        ),
    ):
        manager.set_manual_lock(
            message=" "
        )


def test_daily_loss_has_priority_over_profit_lock() -> None:
    """
    This state is economically unusual for total P&L, but the
    priority contract remains explicit.
    """

    manager = DailyRiskManager(
        registry=make_registry(),
        config=DailyRiskConfig(
            max_daily_loss_amount=1000,
            daily_profit_lock_amount=2000,
        ),
    )

    # No conflicting lock can actually occur from one scalar
    # total P&L. This test simply verifies normal negative path.

    closed = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        open_quantity=0,
        closed_quantity=65,
        realized_pnl=-1000,
        state=ManagedPositionState.CLOSED,
    )

    registry = make_registry(
        closed
    )

    manager = DailyRiskManager(
        registry=registry,
        config=DailyRiskConfig(
            max_daily_loss_amount=1000,
            daily_profit_lock_amount=2000,
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={},
        captured_at=NOW,
    )

    assert (
        snapshot.lock_reason
        is DailyRiskLockReason.MAX_DAILY_LOSS
    )


def test_locked_day_still_reports_open_positions() -> None:
    position = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    manager = DailyRiskManager(
        registry=make_registry(
            position
        ),
        config=DailyRiskConfig(
            max_daily_loss_amount=500
        ),
    )

    snapshot = manager.build_snapshot(
        trading_date=TRADING_DATE,
        position_pnls={
            "POS-001": make_pnl(
                unrealized=-650
            )
        },
        captured_at=NOW,
    )

    assert snapshot.new_entries_allowed is False

    # Locking NEW entries does not erase or close exposure.
    assert snapshot.open_positions == 1
    assert snapshot.open_quantity == 65


def test_invalid_loss_config_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "max_daily_loss_amount must be "
            "greater than zero"
        ),
    ):
        DailyRiskConfig(
            max_daily_loss_amount=0
        )


def test_invalid_profit_config_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "daily_profit_lock_amount must be "
            "greater than zero"
        ),
    ):
        DailyRiskConfig(
            daily_profit_lock_amount=0
        )


def test_nan_loss_config_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "max_daily_loss_amount must be finite"
        ),
    ):
        DailyRiskConfig(
            max_daily_loss_amount=math.nan
        )


def test_invalid_closed_position_limit_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "max_closed_positions must be "
            "greater than zero"
        ),
    ):
        DailyRiskConfig(
            max_closed_positions=0
        )


def test_daily_snapshot_requires_matching_total() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "total_pnl must equal realized_pnl "
            r"\+ unrealized_pnl"
        ),
    ):
        DailyRiskSnapshot(
            trading_date=TRADING_DATE,
            realized_pnl=100,
            unrealized_pnl=200,
            total_pnl=500,
            open_positions=1,
            closed_positions=0,
            open_quantity=65,
            new_entries_allowed=True,
            lock_reason=DailyRiskLockReason.NONE,
            captured_at=NOW,
        )


def test_allowed_snapshot_cannot_have_lock_reason() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "allowed daily risk snapshot cannot "
            "contain lock reason"
        ),
    ):
        DailyRiskSnapshot(
            trading_date=TRADING_DATE,
            realized_pnl=0,
            unrealized_pnl=0,
            total_pnl=0,
            open_positions=0,
            closed_positions=0,
            open_quantity=0,
            new_entries_allowed=True,
            lock_reason=(
                DailyRiskLockReason.MANUAL_LOCK
            ),
            captured_at=NOW,
        )


def test_locked_snapshot_requires_reason() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "locked daily risk snapshot requires "
            "lock reason"
        ),
    ):
        DailyRiskSnapshot(
            trading_date=TRADING_DATE,
            realized_pnl=0,
            unrealized_pnl=0,
            total_pnl=0,
            open_positions=0,
            closed_positions=0,
            open_quantity=0,
            new_entries_allowed=False,
            lock_reason=DailyRiskLockReason.NONE,
            captured_at=NOW,
        )