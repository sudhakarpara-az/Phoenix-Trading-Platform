from dataclasses import replace
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
from src.risk.option_position_price_monitor import (
    OptionPositionPriceMonitor,
    OptionPriceTick,
    PriceUpdateStatus,
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
    symbol: str = (
        "NIFTY50-20260811-24450-CE"
    ),
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=symbol,
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


def make_filled_position(
    *,
    position_id: str = "POS-001",
    security_id: str = "41009",
    symbol: str = (
        "NIFTY50-20260811-24450-CE"
    ),
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
            symbol=symbol,
        ),
        level=EntryLevel.K5,
        quantity=65,
        entry_price=100,
        filled_at=NOW,
    )


def make_managed_position(
    *,
    position_id: str = "POS-001",
    risk_id: str = "RISK-001",
    security_id: str = "41009",
    symbol: str = (
        "NIFTY50-20260811-24450-CE"
    ),
    open_quantity: int = 65,
    closed_quantity: int = 0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    return ManagedPosition(
        risk_id=PositionRiskId(
            risk_id
        ),
        position=make_filled_position(
            position_id=position_id,
            security_id=security_id,
            symbol=symbol,
        ),
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
        stop_loss=None,
        target=None,
        created_at=NOW,
        updated_at=NOW,
    )


def make_registry(
    position: ManagedPosition | None = None,
) -> PositionRegistry:
    registry = PositionRegistry()

    if position is not None:
        registry.register(
            position
        )

    return registry


def test_option_price_tick_creation() -> None:
    tick = OptionPriceTick(
        security_id="41009",
        ltp=112,
        received_at=NOW,
    )

    assert tick.security_id == "41009"
    assert tick.ltp == 112


def test_empty_security_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="security_id cannot be empty",
    ):
        OptionPriceTick(
            security_id=" ",
            ltp=100,
            received_at=NOW,
        )


def test_zero_ltp_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "ltp must be greater than zero"
        ),
    ):
        OptionPriceTick(
            security_id="41009",
            ltp=0,
            received_at=NOW,
        )


def test_nan_ltp_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="ltp must be finite",
    ):
        OptionPriceTick(
            security_id="41009",
            ltp=math.nan,
            received_at=NOW,
        )


def test_open_position_tick_is_accepted() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    assert result.accepted is True

    assert (
        result.status
        is PriceUpdateStatus.ACCEPTED
    )

    assert result.latest_price is not None

    assert (
        result.latest_price.ltp
        == 112
    )


def test_untracked_security_is_ignored() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            make_managed_position()
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="99999",
            ltp=100,
            received_at=NOW,
        )
    )

    assert result.accepted is False

    assert (
        result.status
        is PriceUpdateStatus
        .UNTRACKED_SECURITY
    )

    assert result.latest_price is None


def test_closed_position_tick_is_not_accepted() -> None:
    position = make_managed_position(
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    assert result.accepted is False

    assert (
        result.status
        is PriceUpdateStatus
        .NO_OPEN_POSITION
    )


def test_partial_position_tick_is_accepted() -> None:
    position = make_managed_position(
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    assert result.accepted is True


def test_newer_tick_replaces_previous_price() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            make_managed_position()
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=110,
            received_at=NOW,
        )
    )

    newer_time = (
        NOW
        + timedelta(seconds=1)
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=newer_time,
        )
    )

    assert result.accepted is True

    latest = monitor.get_by_security_id(
        "41009"
    )

    assert latest is not None
    assert latest.ltp == 112

    assert (
        latest.received_at
        == newer_time
    )


def test_older_tick_is_rejected() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            make_managed_position()
        )
    )

    newer = (
        NOW
        + timedelta(seconds=5)
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=newer,
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=85,
            received_at=NOW,
        )
    )

    assert result.accepted is False

    assert (
        result.status
        is PriceUpdateStatus.STALE_TICK
    )

    latest = monitor.get_by_security_id(
        "41009"
    )

    assert latest is not None

    assert latest.ltp == 112


def test_equal_timestamp_tick_is_rejected() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            make_managed_position()
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=110,
            received_at=NOW,
        )
    )

    result = monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=111,
            received_at=NOW,
        )
    )

    assert (
        result.status
        is PriceUpdateStatus.STALE_TICK
    )

    latest = monitor.get_by_security_id(
        "41009"
    )

    assert latest is not None
    assert latest.ltp == 110


def test_get_for_position() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    latest = monitor.get_for_position(
        position.position_id
    )

    assert latest is not None
    assert latest.ltp == 112


def test_unknown_position_has_no_price() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry()
    )

    latest = monitor.get_for_position(
        FilledPositionId(
            "POS-UNKNOWN"
        )
    )

    assert latest is None


def test_require_position_price() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    latest = monitor.require_for_position(
        position.position_id
    )

    assert latest.ltp == 112


def test_require_missing_position_price_raises() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    with pytest.raises(
        LookupError,
        match=(
            "latest option price not available"
        ),
    ):
        monitor.require_for_position(
            position.position_id
        )


def test_price_is_fresh_within_age_limit() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    assert monitor.is_fresh(
        position_id=position.position_id,
        now=(
            NOW
            + timedelta(seconds=2)
        ),
        max_age=timedelta(
            seconds=5
        ),
    ) is True


def test_price_is_stale_after_age_limit() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    assert monitor.is_fresh(
        position_id=position.position_id,
        now=(
            NOW
            + timedelta(seconds=10)
        ),
        max_age=timedelta(
            seconds=5
        ),
    ) is False


def test_price_at_exact_age_limit_is_fresh() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    assert monitor.is_fresh(
        position_id=position.position_id,
        now=(
            NOW
            + timedelta(seconds=5)
        ),
        max_age=timedelta(
            seconds=5
        ),
    ) is True


def test_future_dated_price_is_not_fresh() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=(
                NOW
                + timedelta(seconds=5)
            ),
        )
    )

    assert monitor.is_fresh(
        position_id=position.position_id,
        now=NOW,
        max_age=timedelta(
            seconds=10
        ),
    ) is False


def test_negative_max_age_rejected() -> None:
    position = make_managed_position()

    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            position
        )
    )

    with pytest.raises(
        ValueError,
        match="max_age cannot be negative",
    ):
        monitor.is_fresh(
            position_id=position.position_id,
            now=NOW,
            max_age=timedelta(
                seconds=-1
            ),
        )


def test_tracked_security_ids_only_include_open_positions() -> None:
    registry = PositionRegistry()

    registry.register(
        make_managed_position(
            position_id="POS-001",
            risk_id="RISK-001",
            security_id="41009",
        )
    )

    registry.register(
        make_managed_position(
            position_id="POS-002",
            risk_id="RISK-002",
            security_id="41019",
            symbol=(
                "NIFTY50-20260811-24650-PE"
            ),
            open_quantity=0,
            closed_quantity=65,
            state=ManagedPositionState.CLOSED,
        )
    )

    monitor = OptionPositionPriceMonitor(
        registry=registry
    )

    assert (
        monitor.tracked_security_ids()
        == ("41009",)
    )


def test_same_security_used_by_two_open_positions_is_returned_once() -> None:
    registry = PositionRegistry()

    registry.register(
        make_managed_position(
            position_id="POS-001",
            risk_id="RISK-001",
            security_id="41009",
        )
    )

    registry.register(
        make_managed_position(
            position_id="POS-002",
            risk_id="RISK-002",
            security_id="41009",
        )
    )

    monitor = OptionPositionPriceMonitor(
        registry=registry
    )

    assert (
        monitor.tracked_security_ids()
        == ("41009",)
    )


def test_remove_security_price() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            make_managed_position()
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    removed = monitor.remove_security(
        "41009"
    )

    assert removed is True

    assert (
        monitor.get_by_security_id(
            "41009"
        )
        is None
    )


def test_remove_unknown_security_returns_false() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry()
    )

    assert monitor.remove_security(
        "99999"
    ) is False


def test_latest_prices_returns_tuple() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            make_managed_position()
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    result = monitor.latest_prices()

    assert isinstance(
        result,
        tuple,
    )

    assert len(result) == 1


def test_clear_price_cache() -> None:
    monitor = OptionPositionPriceMonitor(
        registry=make_registry(
            make_managed_position()
        )
    )

    monitor.process_tick(
        OptionPriceTick(
            security_id="41009",
            ltp=112,
            received_at=NOW,
        )
    )

    assert len(
        monitor.latest_prices()
    ) == 1

    monitor.clear()

    assert (
        monitor.latest_prices()
        == ()
    )