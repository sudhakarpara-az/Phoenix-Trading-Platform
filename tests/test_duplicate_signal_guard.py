from datetime import date, datetime, timedelta

import pytest

from src.signals.duplicate_signal_guard import (
    DuplicateSignalGuard,
    SignalFingerprint,
)
from src.strategy.strategy_types import (
    KSLevelName,
    LevelEvent,
    LevelEventType,
)


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
INSTRUMENT_SYMBOL = "NIFTY-24550-CE"


def make_event(
    level: KSLevelName = KSLevelName.K5,
    event_type: LevelEventType = LevelEventType.CROSSED_UP,
    timestamp: datetime | None = None,
) -> LevelEvent:
    event_time = timestamp or datetime(
        2026,
        8,
        7,
        10,
        0,
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
        level_price=24500.0,
        market_price=24501.0,
        timestamp=event_time,
    )


def test_first_event_is_allowed() -> None:
    guard = DuplicateSignalGuard(
        suppression_seconds=5,
    )

    assert guard.allow(
        make_event()
    ) is True


def test_duplicate_inside_window_is_blocked() -> None:
    guard = DuplicateSignalGuard(
        suppression_seconds=5,
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    assert guard.allow(
        make_event(
            timestamp=start,
        )
    ) is True

    assert guard.allow(
        make_event(
            timestamp=start
            + timedelta(seconds=2),
        )
    ) is False


def test_duplicate_at_window_boundary_is_allowed() -> None:
    guard = DuplicateSignalGuard(
        suppression_seconds=5,
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    assert guard.allow(
        make_event(
            timestamp=start,
        )
    ) is True

    assert guard.allow(
        make_event(
            timestamp=start
            + timedelta(seconds=5),
        )
    ) is True


def test_duplicate_after_window_is_allowed() -> None:
    guard = DuplicateSignalGuard(
        suppression_seconds=5,
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
        0,
    )

    guard.allow(
        make_event(
            timestamp=start,
        )
    )

    assert guard.allow(
        make_event(
            timestamp=start
            + timedelta(seconds=6),
        )
    ) is True


def test_different_level_is_not_duplicate() -> None:
    guard = DuplicateSignalGuard()

    timestamp = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    assert guard.allow(
        make_event(
            level=KSLevelName.K5,
            timestamp=timestamp,
        )
    ) is True

    assert guard.allow(
        make_event(
            level=KSLevelName.K6,
            timestamp=timestamp,
        )
    ) is True


def test_different_event_type_is_not_duplicate() -> None:
    guard = DuplicateSignalGuard()

    timestamp = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    assert guard.allow(
        make_event(
            event_type=LevelEventType.CROSSED_UP,
            timestamp=timestamp,
        )
    ) is True

    assert guard.allow(
        make_event(
            event_type=LevelEventType.CROSSED_DOWN,
            timestamp=timestamp,
        )
    ) is True


def test_clear_level_allows_immediate_reentry_event() -> None:
    guard = DuplicateSignalGuard(
        suppression_seconds=30,
    )

    start = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    assert guard.allow(
        make_event(
            level=KSLevelName.K5,
            timestamp=start,
        )
    ) is True

    guard.clear_level(
        KSLevelName.K5
    )

    assert guard.allow(
        make_event(
            level=KSLevelName.K5,
            timestamp=start
            + timedelta(seconds=1),
        )
    ) is True


def test_clear_level_does_not_remove_other_levels() -> None:
    guard = DuplicateSignalGuard()

    timestamp = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    guard.allow(
        make_event(
            level=KSLevelName.K5,
            timestamp=timestamp,
        )
    )

    guard.allow(
        make_event(
            level=KSLevelName.K6,
            timestamp=timestamp,
        )
    )

    guard.clear_level(
        KSLevelName.K5
    )

    assert guard.count() == 1


def test_clear_removes_all_fingerprints() -> None:
    guard = DuplicateSignalGuard()

    guard.allow(
        make_event(
            level=KSLevelName.K5,
        )
    )

    guard.allow(
        make_event(
            level=KSLevelName.K6,
        )
    )

    assert guard.count() == 2

    guard.clear()

    assert guard.count() == 0


def test_invalid_suppression_window_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="suppression_seconds must be greater than zero",
    ):
        DuplicateSignalGuard(
            suppression_seconds=0,
        )


def test_signal_fingerprint_equality() -> None:
    first = SignalFingerprint(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=KSLevelName.K5,
        event_type=LevelEventType.CROSSED_UP,
    )

    second = SignalFingerprint(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=KSLevelName.K5,
        event_type=LevelEventType.CROSSED_UP,
    )

    assert first == second


def test_same_level_on_different_contract_is_not_duplicate() -> None:
    guard = DuplicateSignalGuard(
        suppression_seconds=5,
    )

    timestamp = datetime(
        2026,
        8,
        7,
        10,
        0,
    )

    ce_event = make_event(
        level=KSLevelName.K5,
        timestamp=timestamp,
    )

    pe_event = LevelEvent(
        trading_date=TRADING_DATE,
        instrument_security_id="67890",
        instrument_symbol="NIFTY-24750-PE",
        level=KSLevelName.K5,
        event_type=LevelEventType.CROSSED_UP,
        level_price=24500.0,
        market_price=24501.0,
        timestamp=timestamp,
    )

    assert guard.allow(ce_event) is True
    assert guard.allow(pe_event) is True
