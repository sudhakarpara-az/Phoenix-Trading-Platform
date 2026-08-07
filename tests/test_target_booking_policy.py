import pytest

from src.execution.target_booking_policy import (
    TargetBookingConfig,
    TargetBookingMode,
    TargetBookingPolicy,
)


def test_default_configuration() -> None:
    config = TargetBookingConfig()

    assert (
        config.max_profit_points
        == 30.0
    )

    assert (
        config.ks_target_buffer_points
        == 3.0
    )

    assert (
        config.tick_size
        == 0.05
    )


def test_far_target_is_capped_at_30_points() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100.0,
        mapped_target_price=145.0,
    )

    assert (
        plan.mode
        is TargetBookingMode.FIXED_30_POINTS
    )

    assert (
        plan.target_distance_points
        == 45.0
    )

    assert (
        plan.executable_target_price
        == 130.0
    )


def test_user_example_100_entry_129_target() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100.0,
        mapped_target_price=129.0,
    )

    assert (
        plan.mode
        is TargetBookingMode.NEAR_KS_TARGET
    )

    assert (
        plan.target_distance_points
        == 29.0
    )

    assert (
        plan.executable_target_price
        == 126.0
    )

    assert (
        plan.booking_zone_start
        == 126.0
    )

    assert (
        plan.booking_zone_end
        == 129.0
    )


def test_exactly_30_points_uses_near_ks_target_rule() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100.0,
        mapped_target_price=130.0,
    )

    assert (
        plan.mode
        is TargetBookingMode.NEAR_KS_TARGET
    )

    assert (
        plan.executable_target_price
        == 127.0
    )

    assert (
        plan.booking_zone_end
        == 130.0
    )


def test_just_over_30_uses_fixed_target() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100.0,
        mapped_target_price=130.01,
    )

    assert (
        plan.mode
        is TargetBookingMode.FIXED_30_POINTS
    )

    assert (
        plan.executable_target_price
        == 130.0
    )


def test_20_point_target_books_three_points_before() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100.0,
        mapped_target_price=120.0,
    )

    assert (
        plan.executable_target_price
        == 117.0
    )

    assert (
        plan.booking_zone_start
        == 117.0
    )

    assert (
        plan.booking_zone_end
        == 120.0
    )


def test_actual_fill_price_is_used() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=101.25,
        mapped_target_price=140.0,
    )

    # Distance = 38.75
    # therefore actual fill + 30.
    assert (
        plan.executable_target_price
        == 131.25
    )


def test_near_target_uses_actual_fill_distance() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=105.0,
        mapped_target_price=129.0,
    )

    assert (
        plan.target_distance_points
        == 24.0
    )

    assert (
        plan.executable_target_price
        == 126.0
    )


def test_far_target_booking_zone_is_single_price() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100,
        mapped_target_price=150,
    )

    assert (
        plan.booking_zone_start
        == 130
    )

    assert (
        plan.booking_zone_end
        == 130
    )


def test_near_target_has_booking_zone() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100,
        mapped_target_price=125,
    )

    assert (
        plan.booking_zone_start
        == 122
    )

    assert (
        plan.booking_zone_end
        == 125
    )


def test_fractional_target_rounds_down_to_tick() -> None:
    policy = TargetBookingPolicy(
        TargetBookingConfig(
            max_profit_points=30,
            ks_target_buffer_points=3,
            tick_size=0.05,
        )
    )

    plan = policy.calculate(
        entry_price=100,
        mapped_target_price=129.03,
    )

    # Buffered raw target = 126.03
    # Target should not be pushed farther away.
    assert (
        plan.executable_target_price
        == 126.0
    )

    assert (
        plan.booking_zone_end
        == 129.0
    )


def test_far_fractional_target_uses_entry_plus_30() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100.03,
        mapped_target_price=145,
    )

    # raw = 130.03
    # rounded downward to valid 0.05 tick.
    assert (
        plan.executable_target_price
        == 130.0
    )


def test_target_equal_to_entry_rejected() -> None:
    policy = TargetBookingPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "mapped_target_price must be "
            "above entry_price"
        ),
    ):
        policy.calculate(
            entry_price=100,
            mapped_target_price=100,
        )


def test_target_below_entry_rejected() -> None:
    policy = TargetBookingPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "mapped_target_price must be "
            "above entry_price"
        ),
    ):
        policy.calculate(
            entry_price=100,
            mapped_target_price=95,
        )


def test_target_too_close_for_three_point_buffer_rejected() -> None:
    policy = TargetBookingPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "mapped target is too close to entry"
        ),
    ):
        policy.calculate(
            entry_price=100,
            mapped_target_price=102,
        )


def test_exact_three_point_distance_rejected() -> None:
    policy = TargetBookingPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "mapped target is too close to entry"
        ),
    ):
        policy.calculate(
            entry_price=100,
            mapped_target_price=103,
        )


def test_more_than_three_point_distance_is_valid() -> None:
    policy = TargetBookingPolicy()

    plan = policy.calculate(
        entry_price=100,
        mapped_target_price=103.05,
    )

    assert (
        plan.executable_target_price
        == 100.05
    )


def test_zero_entry_rejected() -> None:
    policy = TargetBookingPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "entry_price must be greater than zero"
        ),
    ):
        policy.calculate(
            entry_price=0,
            mapped_target_price=129,
        )


def test_zero_target_rejected() -> None:
    policy = TargetBookingPolicy()

    with pytest.raises(
        ValueError,
        match=(
            "mapped_target_price must be "
            "greater than zero"
        ),
    ):
        policy.calculate(
            entry_price=100,
            mapped_target_price=0,
        )


def test_invalid_max_profit_points_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "max_profit_points must be "
            "greater than zero"
        ),
    ):
        TargetBookingConfig(
            max_profit_points=0
        )


def test_invalid_buffer_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "ks_target_buffer_points must be "
            "greater than zero"
        ),
    ):
        TargetBookingConfig(
            ks_target_buffer_points=0
        )


def test_buffer_must_be_less_than_max_profit() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "ks_target_buffer_points must be "
            "less than max_profit_points"
        ),
    ):
        TargetBookingConfig(
            max_profit_points=3,
            ks_target_buffer_points=3,
        )


def test_invalid_tick_size_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "tick_size must be greater than zero"
        ),
    ):
        TargetBookingConfig(
            tick_size=0
        )