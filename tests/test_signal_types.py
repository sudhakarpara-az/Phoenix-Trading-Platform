from dataclasses import FrozenInstanceError
from datetime import date, datetime

import pytest

from src.signals.signal_types import (
    SignalDirection,
    SignalId,
    SignalReason,
    SignalState,
    TradingSignal,
)
from src.strategy.strategy_types import EntryLevel


TRADING_DATE = date(2026, 8, 7)


def make_signal() -> TradingSignal:
    return TradingSignal(
        signal_id=SignalId("SIG-20260807-K5-001"),
        trading_date=TRADING_DATE,
        level=EntryLevel.K5,
        direction=SignalDirection.CALL,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24500.0,
        level_price=24500.0,
        reason=SignalReason.CROSS_UP,
        state=SignalState.CREATED,
        generated_at=datetime(
            2026,
            8,
            7,
            10,
            0,
        ),
        is_reentry=False,
    )


def test_signal_creation() -> None:
    signal = make_signal()

    assert signal.level is EntryLevel.K5
    assert signal.direction is SignalDirection.CALL
    assert signal.state is SignalState.CREATED


def test_signal_is_immutable() -> None:
    signal = make_signal()

    with pytest.raises(FrozenInstanceError):
        signal.state = SignalState.QUEUED  # type: ignore[misc]


def test_empty_signal_id_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="signal id cannot be empty",
    ):
        SignalId(" ")


def test_invalid_underlying_price_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="underlying_price must be greater than zero",
    ):
        TradingSignal(
            signal_id=SignalId("TEST"),
            trading_date=TRADING_DATE,
            level=EntryLevel.K5,
            direction=SignalDirection.CALL,
            underlying_symbol="NIFTY 50",
            underlying_security_id="13",
            underlying_price=0,
            level_price=24500.0,
            reason=SignalReason.CROSS_UP,
            state=SignalState.CREATED,
            generated_at=datetime.now(),
        )


def test_invalid_level_price_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="level_price must be greater than zero",
    ):
        TradingSignal(
            signal_id=SignalId("TEST"),
            trading_date=TRADING_DATE,
            level=EntryLevel.K5,
            direction=SignalDirection.PUT,
            underlying_symbol="NIFTY 50",
            underlying_security_id="13",
            underlying_price=24500.0,
            level_price=0,
            reason=SignalReason.CROSS_DOWN,
            state=SignalState.CREATED,
            generated_at=datetime.now(),
        )


def test_call_direction_exists() -> None:
    assert SignalDirection.CALL.value == "CALL"


def test_put_direction_exists() -> None:
    assert SignalDirection.PUT.value == "PUT"


def test_reentry_flag() -> None:
    signal = TradingSignal(
        signal_id=SignalId("SIG-REENTRY"),
        trading_date=TRADING_DATE,
        level=EntryLevel.K7,
        direction=SignalDirection.PUT,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        underlying_price=24400.0,
        level_price=24400.0,
        reason=SignalReason.REENTRY,
        state=SignalState.CREATED,
        generated_at=datetime.now(),
        is_reentry=True,
    )

    assert signal.is_reentry is True


def test_strategy_version_default() -> None:
    signal = make_signal()

    assert signal.strategy_version == "KS_PHOENIX_V1"