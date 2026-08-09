from datetime import date, datetime

import pytest

from src.strategy.daily_ks_level_service import (
    DailyKSLevelService,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    ReferenceCandle,
)


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"

OTHER_INSTRUMENT_SECURITY_ID = "67890"
OTHER_INSTRUMENT_SYMBOL = "NIFTY-24750-PE"


def make_candle(
    trading_date: date = TRADING_DATE,
    instrument_security_id: str = INSTRUMENT_SECURITY_ID,
    instrument_symbol: str = INSTRUMENT_SYMBOL,
) -> ReferenceCandle:
    return ReferenceCandle(
        trading_date=trading_date,
        instrument_security_id=instrument_security_id,
        instrument_symbol=instrument_symbol,
        start_time=datetime(
            trading_date.year,
            trading_date.month,
            trading_date.day,
            9,
            15,
        ),
        end_time=datetime(
            trading_date.year,
            trading_date.month,
            trading_date.day,
            9,
            16,
        ),
        open=24500.0,
        high=24530.0,
        low=24480.0,
        close=24510.0,
    )


def test_service_starts_not_ready() -> None:
    service = DailyKSLevelService()

    assert service.is_ready is False
    assert service.get_levels() is None
    assert service.trading_date is None


def test_calculate_creates_daily_levels() -> None:
    service = DailyKSLevelService()

    levels = service.calculate(
        make_candle(),
        calculated_at=datetime(
            2026,
            8,
            7,
            9,
            20,
            1,
        ),
    )

    assert service.is_ready is True
    assert service.get_levels() is levels
    assert service.trading_date == TRADING_DATE


def test_calculation_preserves_instrument_identity() -> None:
    service = DailyKSLevelService()

    candle = make_candle()

    levels = service.calculate(candle)

    assert (
        levels.instrument_security_id
        == candle.instrument_security_id
    )

    assert (
        levels.instrument_symbol
        == candle.instrument_symbol
    )


def test_calculation_preserves_reference_candle_values() -> None:
    service = DailyKSLevelService()

    candle = make_candle()

    levels = service.calculate(candle)

    assert levels.high_915 == candle.high
    assert levels.low_915 == candle.low
    assert levels.close_915 == candle.close


def test_calculation_contains_base_levels() -> None:
    service = DailyKSLevelService()

    levels = service.calculate(make_candle())

    assert levels.n1 == 24555.0
    assert levels.n2 == 24505.0
    assert levels.c1 == 24530.0
    assert levels.e_level == 24427.0
    assert levels.t_level == 24678.0


def test_calculation_contains_entry_levels() -> None:
    service = DailyKSLevelService()

    levels = service.calculate(make_candle())

    assert levels.k5 > 0
    assert levels.k6 > 0
    assert levels.k7 > 0


def test_entry_level_lookup_works() -> None:
    service = DailyKSLevelService()

    levels = service.calculate(make_candle())

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


def test_target_mapping_is_available() -> None:
    service = DailyKSLevelService()

    levels = service.calculate(make_candle())

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


def test_repeated_calculation_same_day_returns_same_object() -> None:
    service = DailyKSLevelService()

    candle = make_candle()

    first = service.calculate(candle)
    second = service.calculate(candle)

    assert first is second


def test_separate_services_own_ce_and_pe_levels_independently() -> None:
    ce_service = DailyKSLevelService()
    pe_service = DailyKSLevelService()

    ce_candle = make_candle(
        instrument_security_id=INSTRUMENT_SECURITY_ID,
        instrument_symbol=INSTRUMENT_SYMBOL,
    )

    pe_candle = ReferenceCandle(
        trading_date=TRADING_DATE,
        instrument_security_id=(
            OTHER_INSTRUMENT_SECURITY_ID
        ),
        instrument_symbol=(
            OTHER_INSTRUMENT_SYMBOL
        ),
        start_time=datetime(
            2026,
            8,
            7,
            9,
            15,
        ),
        end_time=datetime(
            2026,
            8,
            7,
            9,
            16,
        ),
        open=210.0,
        high=225.0,
        low=195.0,
        close=218.0,
    )

    ce_levels = ce_service.calculate(
        ce_candle,
        calculated_at=datetime(
            2026,
            8,
            7,
            9,
            16,
            1,
        ),
    )

    pe_levels = pe_service.calculate(
        pe_candle,
        calculated_at=datetime(
            2026,
            8,
            7,
            9,
            16,
            1,
        ),
    )

    assert ce_service.is_ready is True
    assert pe_service.is_ready is True

    assert ce_service.trading_date == TRADING_DATE
    assert pe_service.trading_date == TRADING_DATE

    assert ce_service.get_levels() is ce_levels
    assert pe_service.get_levels() is pe_levels

    assert (
        ce_levels.instrument_security_id
        == INSTRUMENT_SECURITY_ID
    )

    assert (
        ce_levels.instrument_symbol
        == INSTRUMENT_SYMBOL
    )

    assert (
        pe_levels.instrument_security_id
        == OTHER_INSTRUMENT_SECURITY_ID
    )

    assert (
        pe_levels.instrument_symbol
        == OTHER_INSTRUMENT_SYMBOL
    )

    assert ce_levels is not pe_levels

    assert ce_levels.k5 != pe_levels.k5
    assert ce_levels.k6 != pe_levels.k6
    assert ce_levels.k7 != pe_levels.k7

    assert (
        ce_service.require_levels()
        is ce_levels
    )

    assert (
        pe_service.require_levels()
        is pe_levels
    )



def test_same_day_different_security_id_requires_reset() -> None:
    service = DailyKSLevelService()

    service.calculate(
        make_candle()
    )

    with pytest.raises(
        RuntimeError,
        match="another instrument",
    ):
        service.calculate(
            make_candle(
                instrument_security_id=(
                    OTHER_INSTRUMENT_SECURITY_ID
                ),
            )
        )


def test_same_day_different_symbol_requires_reset() -> None:
    service = DailyKSLevelService()

    service.calculate(
        make_candle()
    )

    with pytest.raises(
        RuntimeError,
        match="another instrument",
    ):
        service.calculate(
            make_candle(
                instrument_symbol=(
                    OTHER_INSTRUMENT_SYMBOL
                ),
            )
        )


def test_different_day_requires_reset() -> None:
    service = DailyKSLevelService()

    service.calculate(
        make_candle(
            date(2026, 8, 7)
        )
    )

    with pytest.raises(
        RuntimeError,
        match="reset service before calculating a new day",
    ):
        service.calculate(
            make_candle(
                date(2026, 8, 8)
            )
        )


def test_require_levels_before_calculation_fails() -> None:
    service = DailyKSLevelService()

    with pytest.raises(
        RuntimeError,
        match="KS levels are not ready",
    ):
        service.require_levels()


def test_require_levels_after_calculation() -> None:
    service = DailyKSLevelService()

    calculated = service.calculate(
        make_candle()
    )

    required = service.require_levels()

    assert required is calculated


def test_reset_clears_daily_state() -> None:
    service = DailyKSLevelService()

    service.calculate(
        make_candle()
    )

    service.reset()

    assert service.is_ready is False
    assert service.get_levels() is None
    assert service.trading_date is None


def test_reset_allows_next_day_calculation() -> None:
    service = DailyKSLevelService()

    first = service.calculate(
        make_candle(
            date(2026, 8, 7)
        )
    )

    service.reset()

    second = service.calculate(
        make_candle(
            date(2026, 8, 8)
        )
    )

    assert first.trading_date == date(2026, 8, 7)
    assert second.trading_date == date(2026, 8, 8)
    assert first is not second


def test_reset_allows_different_instrument_same_day() -> None:
    service = DailyKSLevelService()

    first = service.calculate(
        make_candle()
    )

    service.reset()

    second = service.calculate(
        make_candle(
            instrument_security_id=(
                OTHER_INSTRUMENT_SECURITY_ID
            ),
            instrument_symbol=(
                OTHER_INSTRUMENT_SYMBOL
            ),
        )
    )

    assert (
        first.instrument_security_id
        == INSTRUMENT_SECURITY_ID
    )

    assert (
        second.instrument_security_id
        == OTHER_INSTRUMENT_SECURITY_ID
    )

    assert (
        first.instrument_symbol
        == INSTRUMENT_SYMBOL
    )

    assert (
        second.instrument_symbol
        == OTHER_INSTRUMENT_SYMBOL
    )

    assert first is not second