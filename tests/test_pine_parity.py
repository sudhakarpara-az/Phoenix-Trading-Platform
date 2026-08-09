from datetime import date, datetime

import pytest

from src.strategy.base_level_calculator import BaseLevelCalculator
from src.strategy.ks_level_calculator import KSLevelCalculator
from src.strategy.strategy_types import ReferenceCandle


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"


def make_reference_candle() -> ReferenceCandle:
    return ReferenceCandle(
        trading_date=TRADING_DATE,
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        instrument_symbol=INSTRUMENT_SYMBOL,
        start_time=datetime(2026, 8, 7, 9, 15),
        end_time=datetime(2026, 8, 7, 9, 16),
        open=24500.0,
        high=24530.0,
        low=24480.0,
        close=24510.0,
    )


def calculate_python_levels():
    candle = make_reference_candle()

    base_levels = BaseLevelCalculator().calculate(
        candle,
        calculated_at=datetime(2026, 8, 7, 9, 20),
    )

    ks_levels = KSLevelCalculator().calculate(
        candle=candle,
        base_levels=base_levels,
        calculated_at=datetime(2026, 8, 7, 9, 20, 1),
    )

    return base_levels, ks_levels


def test_pine_parity_n1() -> None:
    base, _ = calculate_python_levels()

    expected = 24555.0

    assert base.n1 == pytest.approx(expected)


def test_pine_parity_n2() -> None:
    base, _ = calculate_python_levels()

    expected = 24505.0

    assert base.n2 == pytest.approx(expected)


def test_pine_parity_c1() -> None:
    base, _ = calculate_python_levels()

    expected = 24530.0

    assert base.c1 == pytest.approx(expected)


def test_pine_parity_e_level() -> None:
    base, _ = calculate_python_levels()

    expected = 24427.0

    assert base.e_level == pytest.approx(expected)


def test_pine_parity_t_level() -> None:
    base, _ = calculate_python_levels()

    expected = 24678.0

    assert base.t_level == pytest.approx(expected)


def test_pine_parity_k0_swapped_label() -> None:
    _, levels = calculate_python_levels()

    # Pine:
    #
    # ks_k1_calculated_value =
    #     n1 * 0.786 / 0.5
    #
    # KS=k0 displays this value.

    expected = 38600.46

    assert levels.k0 == pytest.approx(expected)


def test_pine_parity_k1_swapped_label() -> None:
    _, levels = calculate_python_levels()

    # Pine:
    #
    # ks0_calculated_value =
    #     n2 * 0.118 / 0.5
    #
    # KS=k1 displays this value.

    expected = 5783.18

    assert levels.k1 == pytest.approx(expected)


def test_pine_parity_k2() -> None:
    _, levels = calculate_python_levels()

    expected = 30822.76464

    assert levels.k2 == pytest.approx(expected)


def test_pine_parity_k3() -> None:
    _, levels = calculate_python_levels()

    expected = 26064.25904

    assert levels.k3 == pytest.approx(expected)


def test_pine_parity_k5() -> None:
    _, levels = calculate_python_levels()

    expected = 22191.82

    assert levels.k5 == pytest.approx(expected)


def test_pine_parity_k6() -> None:
    _, levels = calculate_python_levels()

    expected = 18319.38096

    assert levels.k6 == pytest.approx(expected)


def test_pine_parity_k7() -> None:
    _, levels = calculate_python_levels()

    expected = 13002.9816

    assert levels.k7 == pytest.approx(expected)


def test_pine_level_ordering() -> None:
    _, levels = calculate_python_levels()

    # Based on the current Pine interpolation:
    #
    # raw ks1 > K2 > K3 > K5 > K6 > K7 > raw ks0
    #
    # After the intentional displayed label swap:
    #
    # K0 > K2 > K3 > K5 > K6 > K7 > K1

    assert levels.k0 > levels.k2
    assert levels.k2 > levels.k3
    assert levels.k3 > levels.k5
    assert levels.k5 > levels.k6
    assert levels.k6 > levels.k7
    assert levels.k7 > levels.k1


def test_k5_is_exact_midpoint_of_raw_ks_range() -> None:
    _, levels = calculate_python_levels()

    expected_midpoint = (
        levels.k0 + levels.k1
    ) / 2.0

    assert levels.k5 == pytest.approx(
        expected_midpoint
    )


def test_formula_version_is_locked() -> None:
    _, levels = calculate_python_levels()

    assert levels.formula_version == "KS_PHOENIX_V1"