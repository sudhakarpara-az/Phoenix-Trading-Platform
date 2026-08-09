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
from src.risk.position_pnl_calculator import (
    ExitFill,
    PositionPnLCalculator,
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


def make_position(
    *,
    quantity: int = 65,
    entry_price: float = 100.0,
) -> FilledPosition:
    return FilledPosition(
        position_id=FilledPositionId(
            "POS-M07-T04"
        ),
        signal_id=SignalId(
            "SIG-M07-T04"
        ),
        entry_intent_id=OrderIntentId(
            "ORD-M07-T04"
        ),
        entry_broker_reference=(
            BrokerOrderReference(
                broker_name="DHAN",
                order_id="DHAN-M07-T04",
            )
        ),
        selected_option=make_option(),
        level=EntryLevel.K5,
        quantity=quantity,
        entry_price=entry_price,
        filled_at=NOW,
    )


def test_open_position_profit() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            quantity=65,
            entry_price=100,
        ),
        current_ltp=112,
        calculated_at=NOW,
    )

    assert result.open_quantity == 65
    assert result.closed_quantity == 0

    assert (
        result.pnl.unrealized_points
        == 12
    )

    assert (
        result.pnl.unrealized_pnl
        == 780
    )

    assert (
        result.pnl.realized_pnl
        == 0
    )

    assert (
        result.pnl.total_pnl
        == 780
    )


def test_open_position_loss() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            quantity=65,
            entry_price=100,
        ),
        current_ltp=90,
        calculated_at=NOW,
    )

    assert (
        result.pnl.unrealized_points
        == -10
    )

    assert (
        result.pnl.unrealized_pnl
        == -650
    )

    assert (
        result.pnl.total_pnl
        == -650
    )


def test_break_even_position() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            entry_price=100,
        ),
        current_ltp=100,
        calculated_at=NOW,
    )

    assert (
        result.pnl.unrealized_points
        == 0
    )

    assert (
        result.pnl.unrealized_pnl
        == 0
    )

    assert (
        result.pnl.total_pnl
        == 0
    )


def test_actual_fill_price_is_cost_basis() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            entry_price=100.65
        ),
        current_ltp=112.65,
        calculated_at=NOW,
    )

    assert (
        result.pnl.unrealized_points
        == pytest.approx(12)
    )

    assert (
        result.pnl.unrealized_pnl
        == pytest.approx(780)
    )


def test_two_lot_open_position() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            quantity=130,
            entry_price=100,
        ),
        current_ltp=110,
        calculated_at=NOW,
    )

    assert result.open_quantity == 130

    assert (
        result.pnl.unrealized_pnl
        == 1300
    )


def test_single_realized_exit_fill() -> None:
    calculator = PositionPnLCalculator()

    exit_fill = ExitFill(
        quantity=30,
        price=126,
        filled_at=NOW,
    )

    result = calculator.calculate(
        position=make_position(
            quantity=65,
            entry_price=100,
        ),
        current_ltp=120,
        exit_fills=(
            exit_fill,
        ),
        calculated_at=NOW,
    )

    assert result.closed_quantity == 30
    assert result.open_quantity == 35

    # 26 * 30
    assert (
        result.pnl.realized_pnl
        == 780
    )

    # 20 * 35
    assert (
        result.pnl.unrealized_pnl
        == 700
    )

    assert (
        result.pnl.total_pnl
        == 1480
    )


def test_partial_exit_uses_open_quantity_for_unrealized() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            quantity=65,
            entry_price=100,
        ),
        current_ltp=112,
        exit_fills=(
            ExitFill(
                quantity=30,
                price=126,
                filled_at=NOW,
            ),
        ),
        calculated_at=NOW,
    )

    assert result.open_quantity == 35

    assert (
        result.pnl.unrealized_pnl
        == 420
    )


def test_multiple_exit_fills_realized_pnl() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            quantity=65,
            entry_price=100,
        ),
        current_ltp=115,
        exit_fills=(
            ExitFill(
                quantity=20,
                price=120,
                filled_at=NOW,
            ),
            ExitFill(
                quantity=10,
                price=130,
                filled_at=NOW,
            ),
        ),
        calculated_at=NOW,
    )

    # First:
    # (120 - 100) * 20 = 400
    #
    # Second:
    # (130 - 100) * 10 = 300

    assert (
        result.pnl.realized_pnl
        == 700
    )

    assert result.closed_quantity == 30
    assert result.open_quantity == 35

    # Remaining:
    # (115 - 100) * 35 = 525
    assert (
        result.pnl.unrealized_pnl
        == 525
    )

    assert (
        result.pnl.total_pnl
        == 1225
    )


def test_weighted_average_exit_price() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            quantity=65
        ),
        current_ltp=115,
        exit_fills=(
            ExitFill(
                quantity=20,
                price=120,
                filled_at=NOW,
            ),
            ExitFill(
                quantity=10,
                price=130,
                filled_at=NOW,
            ),
        ),
        calculated_at=NOW,
    )

    expected = (
        (20 * 120)
        + (10 * 130)
    ) / 30

    assert (
        result.average_exit_price
        == pytest.approx(expected)
    )


def test_no_exit_fills_has_no_average_exit_price() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(),
        current_ltp=110,
        calculated_at=NOW,
    )

    assert (
        result.average_exit_price
        is None
    )


def test_fully_closed_position_has_zero_unrealized_pnl() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            quantity=65,
            entry_price=100,
        ),
        current_ltp=150,
        exit_fills=(
            ExitFill(
                quantity=65,
                price=126,
                filled_at=NOW,
            ),
        ),
        calculated_at=NOW,
    )

    assert result.open_quantity == 0
    assert result.closed_quantity == 65

    assert (
        result.pnl.unrealized_pnl
        == 0
    )

    assert (
        result.pnl.realized_pnl
        == 1690
    )

    assert (
        result.pnl.total_pnl
        == 1690
    )


def test_realized_loss() -> None:
    calculator = PositionPnLCalculator()

    result = calculator.calculate(
        position=make_position(
            quantity=65,
            entry_price=100,
        ),
        current_ltp=90,
        exit_fills=(
            ExitFill(
                quantity=30,
                price=85,
                filled_at=NOW,
            ),
        ),
        calculated_at=NOW,
    )

    # (85 - 100) * 30
    assert (
        result.pnl.realized_pnl
        == -450
    )

    # (90 - 100) * 35
    assert (
        result.pnl.unrealized_pnl
        == -350
    )

    assert (
        result.pnl.total_pnl
        == -800
    )


def test_total_exit_quantity_cannot_exceed_position() -> None:
    calculator = PositionPnLCalculator()

    with pytest.raises(
        ValueError,
        match=(
            "total exit fill quantity cannot exceed "
            "position quantity"
        ),
    ):
        calculator.calculate(
            position=make_position(
                quantity=65
            ),
            current_ltp=110,
            exit_fills=(
                ExitFill(
                    quantity=40,
                    price=120,
                    filled_at=NOW,
                ),
                ExitFill(
                    quantity=30,
                    price=125,
                    filled_at=NOW,
                ),
            ),
            calculated_at=NOW,
        )


def test_exit_fill_quantity_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "exit fill quantity must be greater than zero"
        ),
    ):
        ExitFill(
            quantity=0,
            price=126,
            filled_at=NOW,
        )


def test_exit_fill_price_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "exit fill price must be greater than zero"
        ),
    ):
        ExitFill(
            quantity=30,
            price=0,
            filled_at=NOW,
        )


def test_exit_fill_price_must_be_finite() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "exit fill price must be finite"
        ),
    ):
        ExitFill(
            quantity=30,
            price=math.nan,
            filled_at=NOW,
        )


def test_current_ltp_must_be_positive() -> None:
    calculator = PositionPnLCalculator()

    with pytest.raises(
        ValueError,
        match=(
            "current_ltp must be greater than zero"
        ),
    ):
        calculator.calculate(
            position=make_position(),
            current_ltp=0,
            calculated_at=NOW,
        )


def test_negative_current_ltp_rejected() -> None:
    calculator = PositionPnLCalculator()

    with pytest.raises(
        ValueError,
        match=(
            "current_ltp must be greater than zero"
        ),
    ):
        calculator.calculate(
            position=make_position(),
            current_ltp=-1,
            calculated_at=NOW,
        )


def test_nan_current_ltp_rejected() -> None:
    calculator = PositionPnLCalculator()

    with pytest.raises(
        ValueError,
        match="current_ltp must be finite",
    ):
        calculator.calculate(
            position=make_position(),
            current_ltp=math.nan,
            calculated_at=NOW,
        )


def test_infinite_current_ltp_rejected() -> None:
    calculator = PositionPnLCalculator()

    with pytest.raises(
        ValueError,
        match="current_ltp must be finite",
    ):
        calculator.calculate(
            position=make_position(),
            current_ltp=math.inf,
            calculated_at=NOW,
        )