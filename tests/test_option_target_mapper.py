from datetime import (
    date,
    datetime,
    timedelta,
)

import pytest

from src.execution.execution_types import (
    BrokerOrderReference,
    OrderIntentId,
)
from src.execution.position_exit_types import (
    FilledPosition,
    FilledPositionId,
)
from src.execution.target_booking_policy import (
    TargetBookingMode,
)
from src.option_selection.option_types import (
    OptionCandidate,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    OptionType,
    SelectedOption,
)
from src.risk.option_target_mapper import (
    OptionTargetMapper,
    OptionTargetMappingStatus,
)
from src.risk.risk_types import (
    TargetState,
)
from src.signals.signal_types import (
    SignalId,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    KSLevels,
)


TRADING_DATE = date(
    2026,
    8,
    7,
)

EXPIRY = date(
    2026,
    8,
    11,
)

LEVEL_TIME = datetime(
    2026,
    8,
    7,
    9,
    16,
)

FILL_TIME = datetime(
    2026,
    8,
    7,
    10,
    0,
)

MAPPED_AT = (
    FILL_TIME
    + timedelta(seconds=1)
)


def make_option(
    *,
    security_id: str = "41009",
    symbol: str = "NIFTY50-20260811-24450-CE",
    option_type: OptionType = OptionType.CALL,
) -> SelectedOption:
    delta = (
        0.60
        if option_type is OptionType.CALL
        else -0.60
    )

    return SelectedOption(
        candidate=OptionCandidate(
            contract=OptionContract(
                underlying_symbol="NIFTY 50",
                symbol=symbol,
                security_id=security_id,
                option_type=option_type,
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
                received_at=FILL_TIME,
            ),
            greeks=OptionGreeks(
                delta=delta,
                calculated_at=FILL_TIME,
            ),
        ),
        selected_at=FILL_TIME,
        selection_delta_target=0.60,
    )


def make_position(
    *,
    position_id: str = "POS-C09",
    security_id: str = "41009",
    symbol: str = "NIFTY50-20260811-24450-CE",
    option_type: OptionType = OptionType.CALL,
    level: EntryLevel = EntryLevel.K5,
    entry_price: float = 100.0,
    filled_at: datetime = FILL_TIME,
) -> FilledPosition:
    return FilledPosition(
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
            security_id=security_id,
            symbol=symbol,
            option_type=option_type,
        ),
        level=level,
        quantity=65,
        entry_price=entry_price,
        filled_at=filled_at,
    )


def make_levels(
    *,
    trading_date: date = TRADING_DATE,
    security_id: str = "41009",
    symbol: str = "NIFTY50-20260811-24450-CE",
    k3: float = 129.0,
    k5: float = 115.0,
    k6: float = 100.0,
    k7: float = 85.0,
) -> KSLevels:
    return KSLevels(
        trading_date=trading_date,
        instrument_security_id=security_id,
        instrument_symbol=symbol,
        high_915=105.0,
        low_915=95.0,
        close_915=100.0,
        n1=110.0,
        n2=100.0,
        c1=105.0,
        e_level=90.0,
        t_level=120.0,
        k0=160.0,
        k1=40.0,
        k2=140.0,
        k3=k3,
        k5=k5,
        k6=k6,
        k7=k7,
        calculated_at=LEVEL_TIME,
    )


def test_k5_maps_to_same_contract_k3() -> None:
    result = OptionTargetMapper().map_target(
        position=make_position(
            level=EntryLevel.K5,
            entry_price=100,
        ),
        levels=make_levels(
            k3=129,
        ),
        mapped_at=MAPPED_AT,
    )

    assert result.mapped is True

    assert (
        result.status
        is OptionTargetMappingStatus.MAPPED
    )

    mapping = result.mapping

    assert mapping.entry_level is EntryLevel.K5
    assert mapping.target_level is KSLevelName.K3

    assert (
        mapping.mapped_option_target_price
        == 129
    )

    assert (
        mapping.target_definition
        .mapped_target_price
        == 129
    )

    assert (
        mapping.target_definition
        .executable_price
        == 126
    )

    assert (
        mapping.target_definition.state
        is TargetState.ARMED
    )


def test_k6_maps_to_same_contract_k5() -> None:
    result = OptionTargetMapper().map_target(
        position=make_position(
            level=EntryLevel.K6,
            entry_price=90,
        ),
        levels=make_levels(
            k5=115,
        ),
        mapped_at=MAPPED_AT,
    )

    mapping = result.mapping

    assert mapping.target_level is KSLevelName.K5

    assert (
        mapping.mapped_option_target_price
        == 115
    )

    assert (
        mapping.target_definition
        .executable_price
        == 112
    )


def test_k7_maps_to_same_contract_k6() -> None:
    result = OptionTargetMapper().map_target(
        position=make_position(
            level=EntryLevel.K7,
            entry_price=80,
        ),
        levels=make_levels(
            k6=100,
        ),
        mapped_at=MAPPED_AT,
    )

    mapping = result.mapping

    assert mapping.target_level is KSLevelName.K6

    assert (
        mapping.mapped_option_target_price
        == 100
    )

    assert (
        mapping.target_definition
        .executable_price
        == 97
    )


def test_far_ks_target_uses_actual_fill_plus_30() -> None:
    result = OptionTargetMapper().map_target(
        position=make_position(
            level=EntryLevel.K5,
            entry_price=100.65,
        ),
        levels=make_levels(
            k3=140,
        ),
        mapped_at=MAPPED_AT,
    )

    target = (
        result.mapping.target_definition
    )

    assert target.mapped_target_price == 140

    assert (
        target.executable_price
        == pytest.approx(130.65)
    )

    assert (
        target.booking_zone_start
        == pytest.approx(130.65)
    )

    assert (
        target.booking_zone_end
        == pytest.approx(130.65)
    )


def test_near_ks_target_uses_three_point_buffer() -> None:
    result = OptionTargetMapper().map_target(
        position=make_position(
            level=EntryLevel.K5,
            entry_price=100,
        ),
        levels=make_levels(
            k3=129,
        ),
        mapped_at=MAPPED_AT,
    )

    target = (
        result.mapping.target_definition
    )

    assert target.executable_price == 126
    assert target.booking_zone_start == 126
    assert target.booking_zone_end == 129


def test_mapper_uses_target_booking_policy_mode() -> None:
    mapper = OptionTargetMapper()

    near_plan = (
        mapper.target_booking_policy.calculate(
            entry_price=100,
            mapped_target_price=129,
        )
    )

    far_plan = (
        mapper.target_booking_policy.calculate(
            entry_price=100,
            mapped_target_price=140,
        )
    )

    assert (
        near_plan.mode
        is TargetBookingMode.NEAR_KS_TARGET
    )

    assert (
        far_plan.mode
        is TargetBookingMode.FIXED_30_POINTS
    )


def test_call_and_put_same_level_use_own_ks_levels() -> None:
    mapper = OptionTargetMapper()

    call_position = make_position(
        position_id="POS-CALL",
        security_id="41009",
        symbol="NIFTY50-20260811-24450-CE",
        option_type=OptionType.CALL,
        level=EntryLevel.K5,
        entry_price=100,
    )

    put_position = make_position(
        position_id="POS-PUT",
        security_id="41019",
        symbol="NIFTY50-20260811-24650-PE",
        option_type=OptionType.PUT,
        level=EntryLevel.K5,
        entry_price=100,
    )

    call_result = mapper.map_target(
        position=call_position,
        levels=make_levels(
            security_id="41009",
            symbol="NIFTY50-20260811-24450-CE",
            k3=129,
        ),
        mapped_at=MAPPED_AT,
    )

    put_result = mapper.map_target(
        position=put_position,
        levels=make_levels(
            security_id="41019",
            symbol="NIFTY50-20260811-24650-PE",
            k3=128,
        ),
        mapped_at=MAPPED_AT,
    )

    assert (
        call_result.mapping
        .instrument_security_id
        == "41009"
    )

    assert (
        put_result.mapping
        .instrument_security_id
        == "41019"
    )

    assert (
        call_result.mapping
        .mapped_option_target_price
        == 129
    )

    assert (
        put_result.mapping
        .mapped_option_target_price
        == 128
    )

    assert (
        call_result.mapping
        .target_definition
        .executable_price
        == 126
    )

    assert (
        put_result.mapping
        .target_definition
        .executable_price
        == 125
    )


def test_security_id_mismatch_fails_closed() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match="KS levels security ID does not match",
    ):
        mapper.map_target(
            position=make_position(
                security_id="41009"
            ),
            levels=make_levels(
                security_id="41019"
            ),
            mapped_at=MAPPED_AT,
        )


def test_symbol_mismatch_fails_closed() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match="KS levels symbol does not match",
    ):
        mapper.map_target(
            position=make_position(
                symbol=(
                    "NIFTY50-20260811-24450-CE"
                )
            ),
            levels=make_levels(
                symbol=(
                    "NIFTY50-20260811-24500-CE"
                )
            ),
            mapped_at=MAPPED_AT,
        )


def test_trading_date_mismatch_fails_closed() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match="KS levels trading date does not match",
    ):
        mapper.map_target(
            position=make_position(),
            levels=make_levels(
                trading_date=date(
                    2026,
                    8,
                    6,
                )
            ),
            mapped_at=MAPPED_AT,
        )


def test_mapping_before_fill_time_fails_closed() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match=(
            "mapped_at cannot be before "
            "position filled_at"
        ),
    ):
        mapper.map_target(
            position=make_position(),
            levels=make_levels(),
            mapped_at=(
                FILL_TIME
                - timedelta(seconds=1)
            ),
        )


def test_target_at_or_below_entry_fails_closed() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match=(
            "mapped_target_price must be "
            "above entry_price"
        ),
    ):
        mapper.map_target(
            position=make_position(
                level=EntryLevel.K5,
                entry_price=129,
            ),
            levels=make_levels(
                k3=129,
            ),
            mapped_at=MAPPED_AT,
        )


def test_target_too_close_for_three_point_buffer_fails_closed() -> None:
    mapper = OptionTargetMapper()

    with pytest.raises(
        ValueError,
        match=(
            "mapped target is too close to entry "
            "for configured KS target buffer"
        ),
    ):
        mapper.map_target(
            position=make_position(
                level=EntryLevel.K5,
                entry_price=100,
            ),
            levels=make_levels(
                k3=102,
            ),
            mapped_at=MAPPED_AT,
        )


def test_mapping_preserves_position_identity() -> None:
    position = make_position(
        position_id="POS-IDENTITY",
        security_id="41009",
        symbol="NIFTY50-20260811-24450-CE",
    )

    result = OptionTargetMapper().map_target(
        position=position,
        levels=make_levels(),
        mapped_at=MAPPED_AT,
    )

    mapping = result.mapping

    assert (
        mapping.position_id
        == position.position_id
    )

    assert (
        mapping.instrument_security_id
        == position.security_id
    )

    assert (
        mapping.instrument_symbol
        == position.symbol
    )

    assert mapping.mapped_at == MAPPED_AT
