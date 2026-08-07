from datetime import (
    date,
    datetime,
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
from src.risk.exposure_risk_policy import (
    ExposureRiskConfig,
    ExposureRiskPolicy,
    ExposureRiskReason,
)
from src.risk.position_registry import (
    PositionRegistry,
)
from src.risk.risk_types import (
    ManagedPosition,
    ManagedPositionState,
    PositionRiskId,
    StopLossDefinition,
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
    security_id: str,
) -> SelectedOption:
    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=(
                    f"NIFTY-{security_id}-CE"
                ),
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


def make_position(
    *,
    position_id: str,
    risk_id: str,
    security_id: str,
    level: EntryLevel = EntryLevel.K5,
    quantity: int = 65,
    open_quantity: int = 65,
    closed_quantity: int = 0,
    risk_points: float | None = 15.0,
    state: ManagedPositionState = (
        ManagedPositionState.OPEN
    ),
) -> ManagedPosition:
    filled = FilledPosition(
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
            security_id=security_id
        ),
        level=level,
        quantity=quantity,
        entry_price=100,
        filled_at=NOW,
    )

    stop = (
        StopLossDefinition(
            stop_price=(
                100 - risk_points
            ),
            risk_points=risk_points,
        )
        if risk_points is not None
        else None
    )

    return ManagedPosition(
        risk_id=PositionRiskId(
            risk_id
        ),
        position=filled,
        open_quantity=open_quantity,
        closed_quantity=closed_quantity,
        realized_pnl=0,
        state=state,
        stop_loss=stop,
        target=None,
        created_at=NOW,
        updated_at=NOW,
    )


def make_registry(
    *positions: ManagedPosition,
) -> PositionRegistry:
    registry = PositionRegistry()

    for position in positions:
        registry.register(
            position
        )

    return registry


def test_default_config_has_no_limits() -> None:
    config = ExposureRiskConfig()

    assert config.max_open_positions is None

    assert (
        config.max_total_open_quantity
        is None
    )

    assert (
        config.max_position_quantity
        is None
    )

    assert (
        config.max_position_risk_amount
        is None
    )

    assert (
        config.max_total_risk_amount
        is None
    )


def test_new_position_is_eligible_without_limits() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry()
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is True

    assert (
        result.reason
        is ExposureRiskReason.ELIGIBLE
    )

    assert (
        result.proposed_risk_amount
        == 975
    )


def test_per_position_quantity_limit() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry(),
        config=ExposureRiskConfig(
            max_position_quantity=65
        ),
    )

    result = policy.evaluate_new_position(
        quantity=130,
        stop_risk_points=15,
    )

    assert result.eligible is False

    assert (
        result.reason
        is ExposureRiskReason
        .MAX_POSITION_QUANTITY
    )


def test_quantity_equal_to_limit_is_allowed() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry(),
        config=ExposureRiskConfig(
            max_position_quantity=65
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is True


def test_max_open_positions() -> None:
    existing = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            existing
        ),
        config=ExposureRiskConfig(
            max_open_positions=1
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is False

    assert (
        result.reason
        is ExposureRiskReason
        .MAX_OPEN_POSITIONS
    )

    assert (
        result.existing_open_positions
        == 1
    )

    assert (
        result.projected_open_positions
        == 2
    )


def test_closed_position_does_not_count_toward_open_limit() -> None:
    closed = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        open_quantity=0,
        closed_quantity=65,
        state=ManagedPositionState.CLOSED,
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            closed
        ),
        config=ExposureRiskConfig(
            max_open_positions=1
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is True

    assert (
        result.existing_open_positions
        == 0
    )


def test_partial_position_counts_as_open() -> None:
    partial = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            partial
        ),
        config=ExposureRiskConfig(
            max_open_positions=1
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is False

    assert (
        result.reason
        is ExposureRiskReason
        .MAX_OPEN_POSITIONS
    )


def test_total_open_quantity_limit() -> None:
    existing = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        quantity=65,
        open_quantity=65,
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            existing
        ),
        config=ExposureRiskConfig(
            max_total_open_quantity=100
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is False

    assert (
        result.reason
        is ExposureRiskReason
        .MAX_TOTAL_OPEN_QUANTITY
    )

    assert (
        result.existing_open_quantity
        == 65
    )

    assert (
        result.projected_open_quantity
        == 130
    )


def test_partial_position_uses_remaining_quantity() -> None:
    partial = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            partial
        ),
        config=ExposureRiskConfig(
            max_total_open_quantity=100
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is True

    assert (
        result.existing_open_quantity
        == 35
    )

    assert (
        result.projected_open_quantity
        == 100
    )


def test_per_position_risk_limit() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry(),
        config=ExposureRiskConfig(
            max_position_risk_amount=1000
        ),
    )

    result = policy.evaluate_new_position(
        quantity=130,
        stop_risk_points=15,
    )

    # 15 * 130 = 1950
    assert result.eligible is False

    assert (
        result.reason
        is ExposureRiskReason
        .MAX_POSITION_RISK
    )

    assert (
        result.proposed_risk_amount
        == 1950
    )


def test_position_risk_equal_to_limit_allowed() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry(),
        config=ExposureRiskConfig(
            max_position_risk_amount=975
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is True


def test_existing_risk_uses_open_quantity() -> None:
    existing = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        quantity=65,
        open_quantity=35,
        closed_quantity=30,
        risk_points=15,
        state=(
            ManagedPositionState
            .PARTIALLY_EXITED
        ),
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            existing
        )
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    # Existing:
    # 35 * 15 = 525
    assert (
        result.existing_total_risk_amount
        == 525
    )

    # Proposed:
    # 65 * 15 = 975

    assert (
        result.projected_total_risk_amount
        == 1500
    )


def test_aggregate_risk_limit() -> None:
    existing = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        risk_points=15,
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            existing
        ),
        config=ExposureRiskConfig(
            max_total_risk_amount=1500
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    # Existing 975
    # New      975
    # Total   1950
    assert result.eligible is False

    assert (
        result.reason
        is ExposureRiskReason
        .MAX_TOTAL_RISK
    )

    assert (
        result.existing_total_risk_amount
        == 975
    )

    assert (
        result.projected_total_risk_amount
        == 1950
    )


def test_aggregate_risk_equal_to_limit_allowed() -> None:
    existing = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        risk_points=15,
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            existing
        ),
        config=ExposureRiskConfig(
            max_total_risk_amount=1950
        ),
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert result.eligible is True


def test_closed_position_contributes_no_risk() -> None:
    closed = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        open_quantity=0,
        closed_quantity=65,
        risk_points=15,
        state=ManagedPositionState.CLOSED,
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            closed
        )
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert (
        result.existing_total_risk_amount
        == 0
    )


def test_existing_position_without_stop_contributes_zero() -> None:
    existing = make_position(
        position_id="POS-001",
        risk_id="RISK-001",
        security_id="41009",
        risk_points=None,
    )

    policy = ExposureRiskPolicy(
        registry=make_registry(
            existing
        )
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=15,
    )

    assert (
        result.existing_total_risk_amount
        == 0
    )


def test_new_position_requires_stop_risk() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry()
    )

    result = policy.evaluate_new_position(
        quantity=65,
        stop_risk_points=None,
    )

    assert result.eligible is False

    assert (
        result.reason
        is ExposureRiskReason
        .STOP_LOSS_REQUIRED
    )


def test_zero_quantity_rejected() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry()
    )

    result = policy.evaluate_new_position(
        quantity=0,
        stop_risk_points=15,
    )

    assert result.eligible is False

    assert (
        result.reason
        is ExposureRiskReason
        .INVALID_QUANTITY
    )


def test_invalid_stop_risk_rejected() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry()
    )

    with pytest.raises(
        ValueError,
        match=(
            "stop_risk_points must be "
            "greater than zero"
        ),
    ):
        policy.evaluate_new_position(
            quantity=65,
            stop_risk_points=0,
        )


def test_nan_stop_risk_rejected() -> None:
    policy = ExposureRiskPolicy(
        registry=make_registry()
    )

    with pytest.raises(
        ValueError,
        match=(
            "stop_risk_points must be finite"
        ),
    ):
        policy.evaluate_new_position(
            quantity=65,
            stop_risk_points=math.nan,
        )


def test_invalid_open_position_limit() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "max_open_positions must be "
            "greater than zero"
        ),
    ):
        ExposureRiskConfig(
            max_open_positions=0
        )


def test_invalid_total_quantity_limit() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "max_total_open_quantity must be "
            "greater than zero"
        ),
    ):
        ExposureRiskConfig(
            max_total_open_quantity=0
        )


def test_invalid_position_risk_limit() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "max_position_risk_amount must be "
            "greater than zero"
        ),
    ):
        ExposureRiskConfig(
            max_position_risk_amount=0
        )


def test_nan_total_risk_limit_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "max_total_risk_amount must be finite"
        ),
    ):
        ExposureRiskConfig(
            max_total_risk_amount=math.nan
        )