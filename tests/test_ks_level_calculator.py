from datetime import date, datetime

import pytest

from src.strategy.base_level_calculator import (
    BaseLevelCalculator,
)
from src.strategy.ks_level_calculator import (
    KSLevelCalculator,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    ReferenceCandle,
)


TRADING_DATE = date(2026, 8, 7)


def make_candle() -> ReferenceCandle:
    return ReferenceCandle(
        trading_date=TRADING_DATE,
        start_time=datetime(2026, 8, 7, 9, 15),
        end_time=datetime(2026, 8, 7, 9, 20),
        open=24500.0,
        high=24530.0,
        low=24480.0,
        close=24510.0,
    )


def calculate_levels():
    candle = make_candle()

    base = BaseLevelCalculator().calculate(
        candle,
        calculated_at=datetime(2026, 8, 7, 9, 20),
    )

    levels = KSLevelCalculator().calculate(
        candle=candle,
        base_levels=base,
        calculated_at=datetime(2026, 8, 7, 9, 20, 1),
    )

    return candle, base, levels


def test_k0_uses_swapped_k1_calculated_value() -> None:
    _, base, levels = calculate_levels()

    expected = (
        base.n1
        * 0.786
        / 0.5
    )

    assert levels.k0 == pytest.approx(expected)


def test_k1_uses_swapped_ks0_calculated_value() -> None:
    _, base, levels = calculate_levels()

    expected = (
        base.n2
        * 0.118
        / 0.5
    )

    assert levels.k1 == pytest.approx(expected)


def test_k2_formula() -> None:
    _, base, levels = calculate_levels()

    ks0 = base.n2 * 0.118 / 0.5
    ks1 = base.n1 * 0.786 / 0.5

    expected = (
        ks0
        + 0.763 * (ks1 - ks0)
    )

    assert levels.k2 == pytest.approx(expected)


def test_k3_formula() -> None:
    _, base, levels = calculate_levels()

    ks0 = base.n2 * 0.118 / 0.5
    ks1 = base.n1 * 0.786 / 0.5

    expected = (
        ks0
        + 0.618 * (ks1 - ks0)
    )

    assert levels.k3 == pytest.approx(expected)


def test_k5_formula() -> None:
    _, base, levels = calculate_levels()

    ks0 = base.n2 * 0.118 / 0.5
    ks1 = base.n1 * 0.786 / 0.5

    expected = (
        ks0
        + 0.500 * (ks1 - ks0)
    )

    assert levels.k5 == pytest.approx(expected)


def test_k6_formula() -> None:
    _, base, levels = calculate_levels()

    ks0 = base.n2 * 0.118 / 0.5
    ks1 = base.n1 * 0.786 / 0.5

    expected = (
        ks0
        + 0.382 * (ks1 - ks0)
    )

    assert levels.k6 == pytest.approx(expected)


def test_k7_formula() -> None:
    _, base, levels = calculate_levels()

    ks0 = base.n2 * 0.118 / 0.5
    ks1 = base.n1 * 0.786 / 0.5

    expected = (
        ks0
        + 0.220 * (ks1 - ks0)
    )

    assert levels.k7 == pytest.approx(expected)


def test_entry_level_prices_match_ks_levels() -> None:
    _, _, levels = calculate_levels()

    assert (
        levels.entry_level_price(EntryLevel.K5)
        == levels.k5
    )

    assert (
        levels.entry_level_price(EntryLevel.K6)
        == levels.k6
    )

    assert (
        levels.entry_level_price(EntryLevel.K7)
        == levels.k7
    )


def test_target_mapping_is_preserved() -> None:
    _, _, levels = calculate_levels()

    assert (
        levels.target_for(EntryLevel.K5)
        is KSLevelName.K3
    )

    assert (
        levels.target_for(EntryLevel.K6)
        is KSLevelName.K5
    )

    assert (
        levels.target_for(EntryLevel.K7)
        is KSLevelName.K6
    )


def test_reference_values_are_preserved() -> None:
    candle, base, levels = calculate_levels()

    assert levels.high_915 == candle.high
    assert levels.low_915 == candle.low
    assert levels.close_915 == candle.close

    assert levels.n1 == base.n1
    assert levels.n2 == base.n2
    assert levels.c1 == base.c1

    assert levels.e_level == base.e_level
    assert levels.t_level == base.t_level


def test_formula_version() -> None:
    _, _, levels = calculate_levels()

    assert levels.formula_version == "KS_PHOENIX_V1"


def test_mismatched_trading_date_is_rejected() -> None:
    candle = make_candle()

    base = BaseLevelCalculator().calculate(candle)

    different_candle = ReferenceCandle(
        trading_date=date(2026, 8, 8),
        start_time=datetime(2026, 8, 8, 9, 15),
        end_time=datetime(2026, 8, 8, 9, 20),
        open=24500.0,
        high=24530.0,
        low=24480.0,
        close=24510.0,
    )

    with pytest.raises(
        ValueError,
        match="trading_date must match",
    ):
        KSLevelCalculator().calculate(
            candle=different_candle,
            base_levels=base,
        )