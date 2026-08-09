import math

import pytest

from src.risk.risk_types import (
    StopLossState,
)
from src.risk.stop_loss_policy import (
    StopLossConfig,
    StopLossPolicy,
)


def test_default_configuration() -> None:
    config = StopLossConfig()

    assert config.risk_points == 15.0
    assert config.tick_size == 0.05


def test_exact_15_point_stop() -> None:
    policy = StopLossPolicy()

    stop = policy.calculate(
        entry_price=100.65
    )

    assert stop.stop_price == 85.65

    assert (
        stop.risk_points
        == pytest.approx(15.0)
    )

    assert (
        stop.state
        is StopLossState.ARMED
    )


def test_entry_100_stop_is_85() -> None:
    policy = StopLossPolicy()

    stop = policy.calculate(
        entry_price=100.0
    )

    assert stop.stop_price == 85.0

    assert (
        stop.risk_points
        == 15.0
    )


def test_custom_risk_points() -> None:
    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=12.0,
            tick_size=0.05,
        )
    )

    stop = policy.calculate(
        entry_price=100.0
    )

    assert stop.stop_price == 88.0

    assert stop.risk_points == 12.0


def test_rounds_stop_up_to_tick() -> None:
    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15.0,
            tick_size=0.05,
        )
    )

    stop = policy.calculate(
        entry_price=100.63
    )

    # Raw:
    # 100.63 - 15 = 85.63
    #
    # Valid 0.05 tick:
    # 85.65
    assert stop.stop_price == 85.65

    assert (
        stop.risk_points
        == pytest.approx(14.98)
    )


def test_rounding_never_increases_requested_risk() -> None:
    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15.0,
            tick_size=0.05,
        )
    )

    stop = policy.calculate(
        entry_price=100.63
    )

    assert (
        stop.risk_points
        <= 15.0
    )


def test_exact_tick_is_not_changed() -> None:
    policy = StopLossPolicy()

    stop = policy.calculate(
        entry_price=100.65
    )

    assert stop.stop_price == 85.65


def test_different_tick_size() -> None:
    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15.0,
            tick_size=0.10,
        )
    )

    stop = policy.calculate(
        entry_price=100.63
    )

    assert stop.stop_price == 85.70

    assert (
        stop.risk_points
        == pytest.approx(14.93)
    )


def test_entry_price_must_be_positive() -> None:
    policy = StopLossPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "entry_price must be greater than zero"
        ),
    ):
        policy.calculate(
            entry_price=0
        )


def test_negative_entry_price_rejected() -> None:
    policy = StopLossPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "entry_price must be greater than zero"
        ),
    ):
        policy.calculate(
            entry_price=-10
        )


def test_nan_entry_price_rejected() -> None:
    policy = StopLossPolicy()

    with pytest.raises(
        ValueError,
        match="entry_price must be finite",
    ):
        policy.calculate(
            entry_price=math.nan
        )


def test_infinite_entry_price_rejected() -> None:
    policy = StopLossPolicy()

    with pytest.raises(
        ValueError,
        match="entry_price must be finite",
    ):
        policy.calculate(
            entry_price=math.inf
        )


def test_risk_cannot_consume_entire_premium() -> None:
    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "configured risk_points produce "
            "a non-positive stop price"
        ),
    ):
        policy.calculate(
            entry_price=15
        )


def test_risk_cannot_exceed_premium() -> None:
    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            "configured risk_points produce "
            "a non-positive stop price"
        ),
    ):
        policy.calculate(
            entry_price=10
        )


def test_custom_small_risk() -> None:
    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=5,
            tick_size=0.05,
        )
    )

    stop = policy.calculate(
        entry_price=100
    )

    assert stop.stop_price == 95
    assert stop.risk_points == 5


def test_invalid_zero_risk_config() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "risk_points must be greater than zero"
        ),
    ):
        StopLossConfig(
            risk_points=0
        )


def test_negative_risk_config_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "risk_points must be greater than zero"
        ),
    ):
        StopLossConfig(
            risk_points=-1
        )


def test_nan_risk_config_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="risk_points must be finite",
    ):
        StopLossConfig(
            risk_points=math.nan
        )


def test_invalid_zero_tick_size() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "tick_size must be greater than zero"
        ),
    ):
        StopLossConfig(
            tick_size=0
        )


def test_negative_tick_size_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "tick_size must be greater than zero"
        ),
    ):
        StopLossConfig(
            tick_size=-0.05
        )


def test_nan_tick_size_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="tick_size must be finite",
    ):
        StopLossConfig(
            tick_size=math.nan
        )