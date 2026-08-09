from src.risk.filled_position_risk_initializer import (
    FilledPositionRiskInitializer,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.stop_loss_policy import (
    StopLossConfig,
    StopLossPolicy,
)


def test_initializer_exposes_exact_owned_registry() -> None:
    registry = PositionRegistry()

    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15,
            tick_size=0.05,
        )
    )

    initializer = FilledPositionRiskInitializer(
        registry=registry,
        stop_loss_policy=policy,
    )

    assert initializer.registry is registry


def test_initializer_exposes_exact_owned_stop_policy() -> None:
    registry = PositionRegistry()

    policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15,
            tick_size=0.05,
        )
    )

    initializer = FilledPositionRiskInitializer(
        registry=registry,
        stop_loss_policy=policy,
    )

    assert (
        initializer.stop_loss_policy
        is policy
    )

    assert (
        initializer
        .stop_loss_policy
        .config
        .risk_points
        == 15
    )
