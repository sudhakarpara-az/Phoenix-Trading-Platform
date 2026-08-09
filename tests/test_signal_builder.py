from datetime import date, datetime

import pytest

from src.signals.signal_builder import (
    SignalBuilder,
    SignalBuildRequest,
)
from src.signals.signal_types import (
    SignalDirection,
    SignalReason,
    SignalState,
)
from src.strategy.strategy_types import (
    EntryLevel,
    KSLevelName,
    LevelEvent,
    LevelEventType,
)


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"


def make_event(
    level: KSLevelName = KSLevelName.K5,
    event_type: LevelEventType = (
        LevelEventType.CROSSED_UP
    ),
    price: float = 24500.0,
    timestamp: datetime | None = None,
) -> LevelEvent:
    event_time = timestamp or datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    return LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        instrument_symbol=INSTRUMENT_SYMBOL,
        level=level,
        event_type=event_type,
        level_price=price,
        market_price=price + 1.0,
        timestamp=event_time,
    )


def make_request(
    event: LevelEvent | None = None,
    direction: SignalDirection = (
        SignalDirection.CALL
    ),
    is_reentry: bool = False,
) -> SignalBuildRequest:
    return SignalBuildRequest(
        event=event or make_event(),
        direction=direction,
        underlying_symbol="NIFTY 50",
        underlying_security_id="13",
        is_reentry=is_reentry,
    )


def test_build_k5_call_signal() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request()
    )

    assert signal.level is EntryLevel.K5
    assert signal.direction is SignalDirection.CALL
    assert signal.state is SignalState.CREATED
    assert signal.is_reentry is False


def test_build_put_signal() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request(
            direction=SignalDirection.PUT,
        )
    )

    assert signal.direction is SignalDirection.PUT


def test_cross_up_maps_to_cross_up_reason() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request(
            event=make_event(
                event_type=LevelEventType.CROSSED_UP,
            )
        )
    )

    assert signal.reason is SignalReason.CROSS_UP


def test_cross_down_maps_to_cross_down_reason() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request(
            event=make_event(
                event_type=LevelEventType.CROSSED_DOWN,
            )
        )
    )

    assert signal.reason is SignalReason.CROSS_DOWN


def test_touch_maps_to_level_touch_reason() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request(
            event=make_event(
                event_type=LevelEventType.TOUCHED,
            )
        )
    )

    assert signal.reason is SignalReason.LEVEL_TOUCH


def test_reentry_overrides_reason() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request(
            event=make_event(
                event_type=LevelEventType.CROSSED_UP,
            ),
            is_reentry=True,
        )
    )

    assert signal.reason is SignalReason.REENTRY
    assert signal.is_reentry is True


def test_signal_preserves_strategy_instrument_identity() -> None:
    builder = SignalBuilder()

    event = make_event()

    signal = builder.build(
        make_request(
            event=event,
        )
    )

    assert (
        signal.instrument_security_id
        == event.instrument_security_id
    )

    assert (
        signal.instrument_symbol
        == event.instrument_symbol
    )


def test_signal_id_includes_strategy_instrument_security_id() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request()
    )

    assert (
        signal.signal_id.value
        == "SIG-20260807-12345-K5-000001"
    )


def test_signal_preserves_underlying_data() -> None:
    builder = SignalBuilder()

    event = make_event(
        price=24500.0,
    )

    signal = builder.build(
        make_request(
            event=event,
        )
    )

    assert signal.underlying_symbol == "NIFTY 50"
    assert signal.underlying_security_id == "13"
    assert signal.underlying_price == event.market_price
    assert signal.level_price == event.level_price


def test_signal_preserves_timestamp() -> None:
    builder = SignalBuilder()

    timestamp = datetime(
        2026,
        8,
        7,
        11,
        15,
        30,
    )

    signal = builder.build(
        make_request(
            event=make_event(
                timestamp=timestamp,
            )
        )
    )

    assert signal.generated_at == timestamp


def test_signal_id_format() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request()
    )

    assert (
        signal.signal_id.value
        == "SIG-20260807-12345-K5-000001"
    )


def test_signal_ids_increment() -> None:
    builder = SignalBuilder()

    first = builder.build(
        make_request(
            event=make_event(
                level=KSLevelName.K5,
            )
        )
    )

    second = builder.build(
        make_request(
            event=make_event(
                level=KSLevelName.K6,
            )
        )
    )

    assert (
        first.signal_id.value
        == "SIG-20260807-12345-K5-000001"
    )

    assert (
        second.signal_id.value
        == "SIG-20260807-12345-K6-000002"
    )


def test_k6_maps_to_entry_level() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request(
            event=make_event(
                level=KSLevelName.K6,
            )
        )
    )

    assert signal.level is EntryLevel.K6


def test_k7_maps_to_entry_level() -> None:
    builder = SignalBuilder()

    signal = builder.build(
        make_request(
            event=make_event(
                level=KSLevelName.K7,
            )
        )
    )

    assert signal.level is EntryLevel.K7


def test_non_entry_level_is_rejected() -> None:
    builder = SignalBuilder()

    with pytest.raises(
        ValueError,
        match="K3 is not a valid entry level",
    ):
        builder.build(
            make_request(
                event=make_event(
                    level=KSLevelName.K3,
                )
            )
        )


def test_strategy_version_is_preserved() -> None:
    builder = SignalBuilder(
        strategy_version="KS_PHOENIX_V1",
    )

    signal = builder.build(
        make_request()
    )

    assert (
        signal.strategy_version
        == "KS_PHOENIX_V1"
    )


def test_custom_strategy_version() -> None:
    builder = SignalBuilder(
        strategy_version="KS_PHOENIX_V2",
    )

    signal = builder.build(
        make_request()
    )

    assert (
        signal.strategy_version
        == "KS_PHOENIX_V2"
    )


def test_empty_strategy_version_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="strategy_version cannot be empty",
    ):
        SignalBuilder(
            strategy_version=" ",
        )
