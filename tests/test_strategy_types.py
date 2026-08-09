from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest

from src.strategy.strategy_types import (
    EntryLevel,
    KSBaseLevels,
    KSLevelName,
    KSLevels,
    LevelEvent,
    LevelEventType,
    ReferenceCandle,
    StrategySessionState,
)


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"


def make_reference_candle() -> ReferenceCandle:
    return ReferenceCandle(
        trading_date=TRADING_DATE,
        instrument_security_id=INSTRUMENT_SECURITY_ID,
        instrument_symbol=INSTRUMENT_SYMBOL,
        start_time=datetime(2026, 8, 7, 9, 15),
        end_time=datetime(2026, 8, 7, 9, 20),
        open=24500.0,
        high=24530.0,
        low=24480.0,
        close=24510.0,
    )


def make_ks_levels() -> KSLevels:
    return KSLevels(
        trading_date=TRADING_DATE,
        instrument_security_id=INSTRUMENT_SECURITY_ID,
        instrument_symbol=INSTRUMENT_SYMBOL,
        high_915=24530.0,
        low_915=24480.0,
        close_915=24510.0,
        n1=24555.0,
        n2=24505.0,
        c1=24530.0,
        e_level=24427.0,
        t_level=24678.0,
        k0=39000.0,
        k1=5800.0,
        k2=31134.6,
        k3=26317.6,
        k5=22400.0,
        k6=18482.4,
        k7=13103.6,
        calculated_at=datetime(2026, 8, 7, 9, 20),
    )


def test_reference_candle_creation() -> None:
    candle = make_reference_candle()

    assert (
        candle.instrument_security_id
        == INSTRUMENT_SECURITY_ID
    )
    assert candle.instrument_symbol == INSTRUMENT_SYMBOL
    assert candle.trading_date == TRADING_DATE
    assert candle.open == 24500.0
    assert candle.high == 24530.0
    assert candle.low == 24480.0
    assert candle.close == 24510.0


def test_reference_candle_is_immutable() -> None:
    candle = make_reference_candle()

    with pytest.raises(FrozenInstanceError):
        candle.close = 25000.0  # type: ignore[misc]


def test_reference_candle_rejects_high_below_low() -> None:
    with pytest.raises(
        ValueError,
        match="high cannot be lower than low",
    ):
        ReferenceCandle(
            trading_date=TRADING_DATE,
            instrument_security_id=INSTRUMENT_SECURITY_ID,
            instrument_symbol=INSTRUMENT_SYMBOL,
            start_time=datetime(2026, 8, 7, 9, 15),
            end_time=datetime(2026, 8, 7, 9, 20),
            open=24500.0,
            high=24470.0,
            low=24480.0,
            close=24475.0,
        )


def test_reference_candle_rejects_invalid_time() -> None:
    with pytest.raises(
        ValueError,
        match="end_time must be after start_time",
    ):
        ReferenceCandle(
            trading_date=TRADING_DATE,
            instrument_security_id=INSTRUMENT_SECURITY_ID,
            instrument_symbol=INSTRUMENT_SYMBOL,
            start_time=datetime(2026, 8, 7, 9, 20),
            end_time=datetime(2026, 8, 7, 9, 15),
            open=24500.0,
            high=24530.0,
            low=24480.0,
            close=24510.0,
        )


def test_reference_candle_rejects_wrong_date() -> None:
    with pytest.raises(
        ValueError,
        match="start_time must match trading_date",
    ):
        ReferenceCandle(
            trading_date=TRADING_DATE,
            instrument_security_id=INSTRUMENT_SECURITY_ID,
            instrument_symbol=INSTRUMENT_SYMBOL,
            start_time=datetime(2026, 8, 6, 9, 15),
            end_time=datetime(2026, 8, 7, 9, 20),
            open=24500.0,
            high=24530.0,
            low=24480.0,
            close=24510.0,
        )


def test_base_levels_creation() -> None:
    base = KSBaseLevels(
        trading_date=TRADING_DATE,
        instrument_security_id=INSTRUMENT_SECURITY_ID,
        instrument_symbol=INSTRUMENT_SYMBOL,
        n1=24555.0,
        n2=24505.0,
        c1=24530.0,
        e_level=24427.0,
        t_level=24678.0,
        calculated_at=datetime(2026, 8, 7, 9, 20),
    )

    assert base.n1 == 24555.0
    assert base.n2 == 24505.0
    assert base.c1 == 24530.0


def test_ks_level_lookup() -> None:
    levels = make_ks_levels()

    assert levels.get(KSLevelName.K0) == 39000.0
    assert levels.get(KSLevelName.K3) == 26317.6
    assert levels.get(KSLevelName.K5) == 22400.0
    assert levels.get(KSLevelName.K7) == 13103.6


def test_entry_level_lookup() -> None:
    levels = make_ks_levels()

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


def test_target_mapping() -> None:
    levels = make_ks_levels()

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


def test_formula_version_defaults() -> None:
    levels = make_ks_levels()

    assert levels.formula_version == "KS_PHOENIX_V1"


def test_level_event_creation() -> None:
    event = LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id=INSTRUMENT_SECURITY_ID,
        instrument_symbol=INSTRUMENT_SYMBOL,
        level=KSLevelName.K5,
        event_type=LevelEventType.TOUCHED,
        level_price=24500.0,
        market_price=24500.50,
        timestamp=datetime(2026, 8, 7, 10, 0),
    )

    assert (
        event.instrument_security_id
        == INSTRUMENT_SECURITY_ID
    )
    assert event.instrument_symbol == INSTRUMENT_SYMBOL
    assert event.level is KSLevelName.K5
    assert event.event_type is LevelEventType.TOUCHED
    assert event.market_price == 24500.50


def test_entry_levels_are_only_k5_k6_k7() -> None:
    assert list(EntryLevel) == [
        EntryLevel.K5,
        EntryLevel.K6,
        EntryLevel.K7,
    ]


def test_strategy_session_states() -> None:
    assert (
        StrategySessionState.WAITING_FOR_MARKET.value
        == "WAITING_FOR_MARKET"
    )

    assert (
        StrategySessionState.BUILDING_REFERENCE_CANDLE.value
        == "BUILDING_REFERENCE_CANDLE"
    )

    assert (
        StrategySessionState.MONITORING.value
        == "MONITORING"
    )

    assert (
        StrategySessionState.CLOSED.value
        == "CLOSED"
    )
def test_reference_candle_rejects_empty_instrument_identity() -> None:
    with pytest.raises(
        ValueError,
        match="instrument_security_id cannot be empty",
    ):
        ReferenceCandle(
            trading_date=TRADING_DATE,
            instrument_security_id=" ",
            instrument_symbol=INSTRUMENT_SYMBOL,
            start_time=datetime(2026, 8, 7, 9, 15),
            end_time=datetime(2026, 8, 7, 9, 20),
            open=24500.0,
            high=24530.0,
            low=24480.0,
            close=24510.0,
        )


def test_level_event_rejects_empty_instrument_symbol() -> None:
    with pytest.raises(
        ValueError,
        match="instrument_symbol cannot be empty",
    ):
        LevelEvent(
            trading_date=TRADING_DATE,
            instrument_security_id=INSTRUMENT_SECURITY_ID,
            instrument_symbol=" ",
            level=KSLevelName.K5,
            event_type=LevelEventType.TOUCHED,
            level_price=24500.0,
            market_price=24500.50,
            timestamp=datetime(2026, 8, 7, 10, 0),
        )
