from src.risk.daily_risk_manager import (
    DailyRiskManager,
)
from src.risk.exposure_risk_policy import (
    ExposureRiskPolicy,
)
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



def test_exposure_policy_exposes_exact_owned_registry() -> None:
    registry = PositionRegistry()

    policy = ExposureRiskPolicy(
        registry=registry
    )

    assert policy.registry is registry


def test_daily_risk_manager_exposes_exact_owned_registry() -> None:
    registry = PositionRegistry()

    manager = DailyRiskManager(
        registry=registry
    )

    assert manager.registry is registry


def test_m07_entry_components_can_prove_shared_registry() -> None:
    registry = PositionRegistry()

    stop_policy = StopLossPolicy(
        StopLossConfig(
            risk_points=15,
            tick_size=0.05,
        )
    )

    initializer = FilledPositionRiskInitializer(
        registry=registry,
        stop_loss_policy=stop_policy,
    )

    exposure = ExposureRiskPolicy(
        registry=registry
    )

    daily = DailyRiskManager(
        registry=registry
    )

    assert (
        initializer.registry
        is exposure.registry
        is daily.registry
        is registry
    )
