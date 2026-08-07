from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from src.market.market_types import (
    Exchange,
    Instrument,
    MarketTick,
    TickType,
)


def test_create_instrument() -> None:
    instrument = Instrument(
        exchange=Exchange.NFO,
        symbol="NIFTY 28 AUG 25000 CE",
        security_id="123456",
    )

    assert instrument.exchange is Exchange.NFO
    assert instrument.symbol == "NIFTY 28 AUG 25000 CE"
    assert instrument.security_id == "123456"


def test_create_market_tick() -> None:
    timestamp = datetime.now()

    tick = MarketTick(
        exchange=Exchange.NFO,
        symbol="NIFTY 28 AUG 25000 CE",
        security_id="123456",
        ltp=125.50,
        volume=100,
        timestamp=timestamp,
        tick_type=TickType.LTP,
    )

    assert tick.exchange is Exchange.NFO
    assert tick.ltp == 125.50
    assert tick.volume == 100
    assert tick.timestamp == timestamp
    assert tick.tick_type is TickType.LTP


def test_instrument_rejects_empty_symbol() -> None:
    with pytest.raises(ValueError, match="symbol cannot be empty"):
        Instrument(
            exchange=Exchange.NFO,
            symbol=" ",
            security_id="123456",
        )


def test_instrument_rejects_empty_security_id() -> None:
    with pytest.raises(ValueError, match="security_id cannot be empty"):
        Instrument(
            exchange=Exchange.NFO,
            symbol="NIFTY",
            security_id=" ",
        )


def test_market_tick_rejects_zero_ltp() -> None:
    with pytest.raises(ValueError, match="ltp must be greater than zero"):
        MarketTick(
            exchange=Exchange.NFO,
            symbol="NIFTY 28 AUG 25000 CE",
            security_id="123456",
            ltp=0,
            volume=100,
            timestamp=datetime.now(),
        )


def test_market_tick_rejects_negative_volume() -> None:
    with pytest.raises(ValueError, match="volume cannot be negative"):
        MarketTick(
            exchange=Exchange.NFO,
            symbol="NIFTY 28 AUG 25000 CE",
            security_id="123456",
            ltp=125.50,
            volume=-1,
            timestamp=datetime.now(),
        )


def test_market_tick_is_immutable() -> None:
    tick = MarketTick(
        exchange=Exchange.NSE,
        symbol="NIFTY 50",
        security_id="13",
        ltp=24850.00,
        volume=0,
        timestamp=datetime.now(),
    )

    with pytest.raises(FrozenInstanceError):
        tick.ltp = 24900.00  # type: ignore[misc]