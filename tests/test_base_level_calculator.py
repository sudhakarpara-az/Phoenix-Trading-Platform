from datetime import date, datetime

from src.strategy.base_level_calculator import (
    BaseLevelCalculator,
)
from src.strategy.strategy_types import ReferenceCandle


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"


def make_candle(
    high: float = 24530.0,
    low: float = 24480.0,
    open_price: float = 24500.0,
    close: float = 24510.0,
) -> ReferenceCandle:
    return ReferenceCandle(
        trading_date=TRADING_DATE,
        instrument_security_id=INSTRUMENT_SECURITY_ID,
        instrument_symbol=INSTRUMENT_SYMBOL,
        start_time=datetime(2026, 8, 7, 9, 15),
        end_time=datetime(2026, 8, 7, 9, 16),
        open=open_price,
        high=high,
        low=low,
        close=close,
    )


def test_calculates_n1() -> None:
    calculator = BaseLevelCalculator()

    levels = calculator.calculate(
        make_candle()
    )

    assert levels.n1 == 24555.0


def test_calculates_n2() -> None:
    calculator = BaseLevelCalculator()

    levels = calculator.calculate(
        make_candle()
    )

    assert levels.n2 == 24505.0


def test_calculates_c1() -> None:
    calculator = BaseLevelCalculator()

    levels = calculator.calculate(
        make_candle()
    )

    assert levels.c1 == 24530.0


def test_calculates_e_level_using_floor() -> None:
    calculator = BaseLevelCalculator()

    levels = calculator.calculate(
        make_candle()
    )

    # floor(24505 * 3.2 / 1000)
    # floor(78.416)
    # = 78
    #
    # E = 24505 - 78
    assert levels.e_level == 24427.0


def test_calculates_t_level_using_floor() -> None:
    calculator = BaseLevelCalculator()

    levels = calculator.calculate(
        make_candle()
    )

    # floor(24505 * 7.1 / 1000)
    # floor(173.9855)
    # = 173
    #
    # T = 24505 + 173
    assert levels.t_level == 24678.0


def test_calculated_at_can_be_supplied() -> None:
    calculator = BaseLevelCalculator()

    calculated_at = datetime(
        2026,
        8,
        7,
        9,
        20,
        1,
    )

    levels = calculator.calculate(
        make_candle(),
        calculated_at=calculated_at,
    )

    assert levels.calculated_at == calculated_at


def test_trading_date_is_preserved() -> None:
    calculator = BaseLevelCalculator()

    levels = calculator.calculate(
        make_candle()
    )

    assert levels.trading_date == TRADING_DATE


def test_instrument_identity_is_preserved() -> None:
    calculator = BaseLevelCalculator()

    levels = calculator.calculate(
        make_candle()
    )

    assert (
        levels.instrument_security_id
        == INSTRUMENT_SECURITY_ID
    )

    assert (
        levels.instrument_symbol
        == INSTRUMENT_SYMBOL
    )


def test_close_price_does_not_change_base_formula() -> None:
    """
    The current Pine formulas use high and low for
    N1/N2 calculations.

    close915 is captured separately but does not affect
    N1/N2/C1/E/T.
    """

    calculator = BaseLevelCalculator()

    first = calculator.calculate(
        make_candle(
            close=24510.0,
        )
    )

    second = calculator.calculate(
        make_candle(
            close=24520.0,
        )
    )

    assert first.n1 == second.n1
    assert first.n2 == second.n2
    assert first.c1 == second.c1
    assert first.e_level == second.e_level
    assert first.t_level == second.t_level


def test_different_range_changes_levels_correctly() -> None:
    calculator = BaseLevelCalculator()

    candle = make_candle(
        high=25000.0,
        low=24900.0,
        open_price=24950.0,
        close=24975.0,
    )

    levels = calculator.calculate(candle)

    # Range = 100
    # Half = 50
    #
    # N1 = 25000 + 50 = 25050
    # N2 = 24900 + 50 = 24950
    # C1 = 25000
    assert levels.n1 == 25050.0
    assert levels.n2 == 24950.0
    assert levels.c1 == 25000.0


def test_e_and_t_adjustments_are_integer_floor_values() -> None:
    calculator = BaseLevelCalculator()

    candle = make_candle(
        high=25000.0,
        low=24900.0,
        open_price=24950.0,
        close=24975.0,
    )

    levels = calculator.calculate(candle)

    # N2 = 24950

    # E:
    # floor(24950 * 3.2 / 1000)
    # floor(79.84) = 79

    assert levels.e_level == 24871.0

    # T:
    # floor(24950 * 7.1 / 1000)
    # floor(177.145) = 177

    assert levels.t_level == 25127.0