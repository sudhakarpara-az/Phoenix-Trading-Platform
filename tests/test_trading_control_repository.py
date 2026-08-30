from datetime import datetime

from src.app.container import (
    build_persistence_foundation,
)
from src.database.engine import (
    DatabaseConfig,
)


NOW = datetime(
    2026,
    8,
    10,
    12,
    0,
)

LATER = datetime(
    2026,
    8,
    10,
    12,
    5,
)


def test_trading_control_repository_add_update_round_trip():
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    try:
        repository = (
            persistence
            .trading_control_repository
        )

        stopped = repository.set_for_account(
            broker="DHAN",
            account_id="A1",
            state="EXIT_AND_STOP",
            message="operator stop",
            changed_at=NOW,
        )

        assert stopped.state == "EXIT_AND_STOP"

        loaded = repository.get_for_account(
            broker="DHAN",
            account_id="A1",
        )

        assert loaded is not None
        assert loaded.state == "EXIT_AND_STOP"
        assert loaded.message == "operator stop"

        active = repository.set_for_account(
            broker="DHAN",
            account_id="A1",
            state="ACTIVE",
            message=None,
            changed_at=LATER,
        )

        assert active.control_id == stopped.control_id

        reloaded = repository.get_for_account(
            broker="DHAN",
            account_id="A1",
        )

        assert reloaded is not None
        assert reloaded.state == "ACTIVE"
        assert reloaded.changed_at == LATER

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_trading_control_is_account_scoped():
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    try:
        repository = (
            persistence
            .trading_control_repository
        )

        repository.set_for_account(
            broker="DHAN",
            account_id="A1",
            state="EXIT_AND_STOP",
            message=None,
            changed_at=NOW,
        )

        repository.set_for_account(
            broker="DHAN",
            account_id="A2",
            state="ACTIVE",
            message=None,
            changed_at=NOW,
        )

        first = repository.get_for_account(
            broker="DHAN",
            account_id="A1",
        )

        second = repository.get_for_account(
            broker="DHAN",
            account_id="A2",
        )

        assert first is not None
        assert second is not None

        assert first.state == "EXIT_AND_STOP"
        assert second.state == "ACTIVE"

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
