from datetime import datetime

import math
import pytest

from src.execution.position_exit_types import (
    FilledPositionId,
)
from src.risk.option_target_mapper import (
    OptionTargetMapper,
    OptionTargetMapping,
    OptionTargetMappingStatus,
    UnderlyingTarget,
    UnderlyingTargetDirection,
)


NOW = datetime(
    2026,
    8,
    7,
    14,
    30,
)


def make_target(
    *,
    target_price: float = 24650,
    direction: UnderlyingTargetDirection = (
        UnderlyingTargetDirection
        .ABOVE_OR_EQUAL
    ),
    level_name: str = "K3",
) -> UnderlyingTarget:
    return UnderlyingTarget(
        target_price=target_price,
        direction=direction,
        level_name=level_name,
    )


def test_underlying_target_creation() -> None:
    target = make_target()

    assert target.target_price == 24650

    assert (
        target.direction
        is UnderlyingTargetDirection
        .ABOVE_OR_EQUAL
    )

    assert target.level_name == "K3"


def test_invalid_underlying_target_price_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "underlying target price must be "
            "greater than zero"
        ),
    ):
        make_target(
            target_price=0
        )


def test_empty_level_name_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="level_name cannot be empty",
    ):
        make_target(
            level_name=" "
        )


def test_above_or_equal_not_reached() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            target_price=24650,
        ),
        current_underlying_price=24640,
        current_option_ltp=125,
        evaluated_at=NOW,
    )

    assert result.mapped is False

    assert (
        result.status
        is OptionTargetMappingStatus
        .UNDERLYING_NOT_REACHED
    )

    assert result.mapping is None


def test_above_or_equal_reached_at_exact_price() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            target_price=24650,
        ),
        current_underlying_price=24650,
        current_option_ltp=129,
        evaluated_at=NOW,
    )

    assert result.mapped is True

    assert (
        result.status
        is OptionTargetMappingStatus.MAPPED
    )


def test_above_or_equal_reached_above_price() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            target_price=24650,
        ),
        current_underlying_price=24655,
        current_option_ltp=131,
        evaluated_at=NOW,
    )

    assert result.mapped is True


def test_below_or_equal_not_reached() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            target_price=24500,
            direction=(
                UnderlyingTargetDirection
                .BELOW_OR_EQUAL
            ),
        ),
        current_underlying_price=24510,
        current_option_ltp=120,
        evaluated_at=NOW,
    )

    assert (
        result.status
        is OptionTargetMappingStatus
        .UNDERLYING_NOT_REACHED
    )


def test_below_or_equal_reached_at_exact_price() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            target_price=24500,
            direction=(
                UnderlyingTargetDirection
                .BELOW_OR_EQUAL
            ),
        ),
        current_underlying_price=24500,
        current_option_ltp=126,
        evaluated_at=NOW,
    )

    assert result.mapped is True


def test_below_or_equal_reached_below_price() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            target_price=24500,
            direction=(
                UnderlyingTargetDirection
                .BELOW_OR_EQUAL
            ),
        ),
        current_underlying_price=24490,
        current_option_ltp=128,
        evaluated_at=NOW,
    )

    assert result.mapped is True


def test_mapping_uses_observed_option_ltp() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            target_price=24650,
        ),
        current_underlying_price=24652,
        current_option_ltp=129,
        evaluated_at=NOW,
    )

    assert result.mapping is not None

    assert (
        result.mapping
        .underlying_target_price
        == 24650
    )

    assert (
        result.mapping
        .underlying_price_at_mapping
        == 24652
    )

    assert (
        result.mapping
        .option_price_at_mapping
        == 129
    )

    assert (
        result.mapping
        .mapped_option_target_price
        == 129
    )


def test_mapping_never_uses_underlying_as_option_target() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            target_price=24650,
        ),
        current_underlying_price=24650,
        current_option_ltp=129,
        evaluated_at=NOW,
    )

    assert result.mapping is not None

    assert (
        result.mapping
        .mapped_option_target_price
        != result.mapping
        .underlying_target_price
    )

    assert (
        result.mapping
        .mapped_option_target_price
        == 129
    )


def test_missing_option_price_blocks_mapping() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(),
        current_underlying_price=24650,
        current_option_ltp=None,
        evaluated_at=NOW,
    )

    assert result.mapped is False

    assert (
        result.status
        is OptionTargetMappingStatus
        .OPTION_PRICE_NOT_AVAILABLE
    )

    assert result.mapping is None


def test_invalid_option_price_rejected_after_target_reached() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match=(
            "current option LTP must be "
            "greater than zero"
        ),
    ):
        mapper.map_target(
            position_id=FilledPositionId(
                "POS-T09"
            ),
            target=make_target(),
            current_underlying_price=24650,
            current_option_ltp=0,
            evaluated_at=NOW,
        )


def test_nan_option_price_rejected() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match=(
            "current option LTP must be finite"
        ),
    ):
        mapper.map_target(
            position_id=FilledPositionId(
                "POS-T09"
            ),
            target=make_target(),
            current_underlying_price=24650,
            current_option_ltp=math.nan,
            evaluated_at=NOW,
        )


def test_invalid_underlying_price_rejected() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match=(
            "current underlying price must be "
            "greater than zero"
        ),
    ):
        mapper.map_target(
            position_id=FilledPositionId(
                "POS-T09"
            ),
            target=make_target(),
            current_underlying_price=0,
            current_option_ltp=129,
            evaluated_at=NOW,
        )


def test_nan_underlying_price_rejected() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match=(
            "current underlying price must be finite"
        ),
    ):
        mapper.map_target(
            position_id=FilledPositionId(
                "POS-T09"
            ),
            target=make_target(),
            current_underlying_price=math.nan,
            current_option_ltp=129,
            evaluated_at=NOW,
        )


def test_mapping_preserves_position_id() -> None:
    mapper = OptionTargetMapper()

    position_id = FilledPositionId(
        "POS-MAPPING-001"
    )

    result = mapper.map_target(
        position_id=position_id,
        target=make_target(),
        current_underlying_price=24650,
        current_option_ltp=129,
        evaluated_at=NOW,
    )

    assert result.mapping is not None

    assert (
        result.mapping.position_id
        == position_id
    )


def test_mapping_preserves_level_name() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(
            level_name="K3"
        ),
        current_underlying_price=24650,
        current_option_ltp=129,
        evaluated_at=NOW,
    )

    assert result.mapping is not None

    assert (
        result.mapping.level_name
        == "K3"
    )


def test_mapping_timestamp_is_preserved() -> None:
    mapper = OptionTargetMapper()

    result = mapper.map_target(
        position_id=FilledPositionId(
            "POS-T09"
        ),
        target=make_target(),
        current_underlying_price=24650,
        current_option_ltp=129,
        evaluated_at=NOW,
    )

    assert result.mapping is not None

    assert (
        result.mapping.mapped_at
        == NOW
    )


def test_mapping_object_rejects_mismatched_option_target() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "mapped_option_target_price must equal "
            "observed option price at mapping"
        ),
    ):
        OptionTargetMapping(
            position_id=FilledPositionId(
                "POS-T09"
            ),
            underlying_target_price=24650,
            underlying_price_at_mapping=24650,
            option_price_at_mapping=129,
            mapped_option_target_price=24650,
            mapped_at=NOW,
            level_name="K3",
        )