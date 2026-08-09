from datetime import date, datetime

import pytest

from src.signals.level_lock_manager import (
    LevelLock,
    LevelLockManager,
)
from src.strategy.strategy_types import EntryLevel


TRADING_DATE = date(2026, 8, 7)

INSTRUMENT_SECURITY_ID = "12345"
OTHER_INSTRUMENT_SECURITY_ID = "67890"


def lock_time() -> datetime:
    return datetime(
        2026,
        8,
        7,
        10,
        0,
    )


def test_manager_starts_empty() -> None:
    manager = LevelLockManager()

    assert manager.count() == 0
    assert manager.active_levels() == ()
    assert manager.trading_date is None


def test_acquire_k5_lock() -> None:
    manager = LevelLockManager()

    acquired = manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
        reference_id="SIG-K5-001",
    )

    assert acquired is True

    assert manager.is_locked(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    ) is True

    assert manager.count() == 1


def test_duplicate_k5_lock_is_rejected() -> None:
    manager = LevelLockManager()

    first = manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    second = manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    assert first is True
    assert second is False
    assert manager.count() == 1


def test_different_levels_can_be_locked() -> None:
    manager = LevelLockManager()

    assert manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    ) is True

    assert manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K6,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    ) is True

    assert manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K7,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    ) is True

    assert manager.count() == 3


def test_release_lock() -> None:
    manager = LevelLockManager()

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    released = manager.release(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    )

    assert released is True

    assert manager.is_locked(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    ) is False

    assert manager.count() == 0


def test_release_unknown_lock_returns_false() -> None:
    manager = LevelLockManager()

    assert manager.release(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    ) is False


def test_reentry_possible_after_release() -> None:
    manager = LevelLockManager()

    assert manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    ) is True

    assert manager.release(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    ) is True

    assert manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=datetime(
            2026,
            8,
            7,
            11,
            0,
        ),
        reference_id="SIG-K5-REENTRY",
    ) is True

    assert manager.is_locked(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    ) is True


def test_get_lock_returns_metadata() -> None:
    manager = LevelLockManager()

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K6,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
        reference_id="SIG-K6-001",
    )

    lock = manager.get_lock(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K6,
    )

    assert isinstance(lock, LevelLock)

    assert (
        lock.instrument_security_id
        == INSTRUMENT_SECURITY_ID
    )

    assert lock.level is EntryLevel.K6
    assert lock.trading_date == TRADING_DATE
    assert lock.locked_at == lock_time()
    assert lock.reference_id == "SIG-K6-001"


def test_get_unknown_lock_returns_none() -> None:
    manager = LevelLockManager()

    assert manager.get_lock(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K7,
    ) is None


def test_active_levels_returns_locked_levels() -> None:
    manager = LevelLockManager()

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K7,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    levels = manager.active_levels(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        )
    )

    assert set(levels) == {
        EntryLevel.K5,
        EntryLevel.K7,
    }


def test_clear_removes_all_locks() -> None:
    manager = LevelLockManager()

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K6,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    manager.clear()

    assert manager.count() == 0
    assert manager.active_levels() == ()
    assert manager.trading_date is None


def test_empty_reference_id_is_rejected() -> None:
    manager = LevelLockManager()

    with pytest.raises(
        ValueError,
        match="reference_id cannot be empty",
    ):
        manager.acquire(
            instrument_security_id=(
                INSTRUMENT_SECURITY_ID
            ),
            level=EntryLevel.K5,
            trading_date=TRADING_DATE,
            locked_at=lock_time(),
            reference_id=" ",
        )


def test_trading_date_is_initialized_on_first_lock() -> None:
    manager = LevelLockManager()

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    assert manager.trading_date == TRADING_DATE


def test_date_change_with_active_lock_is_rejected() -> None:
    manager = LevelLockManager()

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "cannot change trading date while "
            "level locks are active"
        ),
    ):
        manager.acquire(
            instrument_security_id=(
                INSTRUMENT_SECURITY_ID
            ),
            level=EntryLevel.K6,
            trading_date=date(2026, 8, 8),
            locked_at=datetime(
                2026,
                8,
                8,
                10,
                0,
            ),
        )


def test_date_can_change_after_all_locks_released() -> None:
    manager = LevelLockManager()

    manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    manager.release(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    )

    acquired = manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K6,
        trading_date=date(2026, 8, 8),
        locked_at=datetime(
            2026,
            8,
            8,
            10,
            0,
        ),
    )

    assert acquired is True
    assert manager.trading_date == date(2026, 8, 8)


def test_same_level_can_be_locked_for_different_contracts() -> None:
    manager = LevelLockManager()

    first = manager.acquire(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    second = manager.acquire(
        instrument_security_id=(
            OTHER_INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
        trading_date=TRADING_DATE,
        locked_at=lock_time(),
    )

    assert first is True
    assert second is True
    assert manager.count() == 2

    assert manager.is_locked(
        instrument_security_id=(
            INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    ) is True

    assert manager.is_locked(
        instrument_security_id=(
            OTHER_INSTRUMENT_SECURITY_ID
        ),
        level=EntryLevel.K5,
    ) is True
