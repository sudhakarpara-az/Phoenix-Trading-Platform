"""
Phoenix M08-T02 Database Engine & Session Management tests.
"""

from pathlib import Path

import pytest

from sqlalchemy import (
    text,
)

from src.database.engine import (
    DatabaseConfig,
    DatabaseEngine,
)
from src.database.session import (
    DatabaseSessionManager,
)


def make_memory_runtime():
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    database.start()

    sessions = DatabaseSessionManager(
        database_engine=database
    )

    sessions.start()

    return (
        database,
        sessions,
    )


# ============================================================
# DatabaseConfig
# ============================================================


def test_default_database_config() -> None:
    config = DatabaseConfig()

    assert (
        config.url
        == "sqlite+pysqlite:///data/phoenix.db"
    )

    assert config.echo is False

    assert (
        config.create_parent_directory
        is True
    )


def test_empty_database_url_rejected() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "database url cannot be empty"
        ),
    ):
        DatabaseConfig(
            url=" "
        )


def test_database_url_trimmed() -> None:
    config = DatabaseConfig(
        url=(
            "  sqlite+pysqlite:///:memory:  "
        )
    )

    assert (
        config.url
        == "sqlite+pysqlite:///:memory:"
    )


def test_memory_config() -> None:
    config = (
        DatabaseConfig.sqlite_memory()
    )

    assert config.is_sqlite is True

    assert (
        config.is_memory_sqlite
        is True
    )

    assert config.sqlite_path is None


def test_file_config() -> None:
    config = (
        DatabaseConfig.sqlite_file(
            "data/test.db"
        )
    )

    assert config.is_sqlite is True

    assert (
        config.is_memory_sqlite
        is False
    )

    assert (
        config.sqlite_path
        == Path(
            "data/test.db"
        )
    )


def test_non_sqlite_config_has_no_sqlite_path() -> None:
    config = DatabaseConfig(
        url=(
            "postgresql+psycopg://"
            "user:pass@localhost/phoenix"
        ),
        create_parent_directory=False,
    )

    assert config.is_sqlite is False
    assert config.sqlite_path is None


# ============================================================
# Engine lifecycle
# ============================================================


def test_engine_starts_not_started() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    assert database.started is False


def test_start_creates_engine() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    assert engine is not None
    assert database.started is True

    database.dispose()


def test_start_is_idempotent() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    first = database.start()
    second = database.start()

    assert first is second

    database.dispose()


def test_require_engine_before_start_rejected() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "database engine has not been started"
        ),
    ):
        database.require_engine()


def test_health_check() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    database.start()

    assert database.health_check() is True

    database.dispose()


def test_dispose_stops_engine() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    database.start()

    assert database.started is True

    database.dispose()

    assert database.started is False


def test_dispose_is_idempotent() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    database.start()

    database.dispose()
    database.dispose()

    assert database.started is False


# ============================================================
# File-backed SQLite
# ============================================================


def test_file_database_parent_directory_created(
    tmp_path,
) -> None:
    database_path = (
        tmp_path
        / "nested"
        / "phoenix.db"
    )

    database = DatabaseEngine(
        DatabaseConfig.sqlite_file(
            database_path
        )
    )

    database.start()

    # Engine construction prepares directory.
    assert (
        database_path.parent.exists()
        is True
    )

    # Actual DB file is created when first connection occurs.
    assert database.health_check() is True

    assert database_path.exists() is True

    database.dispose()


def test_database_file_not_required_for_memory() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    database.start()

    assert (
        database.config.sqlite_path
        is None
    )

    database.dispose()


# ============================================================
# SQLite configuration
# ============================================================


def test_sqlite_foreign_keys_enabled() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    with engine.connect() as connection:
        enabled = connection.execute(
            text(
                "PRAGMA foreign_keys"
            )
        ).scalar_one()

    assert enabled == 1

    database.dispose()


def test_sqlite_busy_timeout_configured() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    engine = database.start()

    with engine.connect() as connection:
        timeout = connection.execute(
            text(
                "PRAGMA busy_timeout"
            )
        ).scalar_one()

    assert timeout == 5000

    database.dispose()


# ============================================================
# Session manager
# ============================================================


def test_session_manager_requires_engine_start() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    sessions = DatabaseSessionManager(
        database_engine=database
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "database engine has not been started"
        ),
    ):
        sessions.start()


def test_session_manager_start() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    database.start()

    sessions = DatabaseSessionManager(
        database_engine=database
    )

    assert sessions.started is False

    sessions.start()

    assert sessions.started is True

    sessions.stop()
    database.dispose()


def test_session_manager_start_idempotent() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    database.start()

    sessions = DatabaseSessionManager(
        database_engine=database
    )

    sessions.start()
    sessions.start()

    assert sessions.started is True

    sessions.stop()
    database.dispose()


def test_create_session_before_start_rejected() -> None:
    database = DatabaseEngine(
        DatabaseConfig.sqlite_memory()
    )

    sessions = DatabaseSessionManager(
        database_engine=database
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "database session manager "
            "has not been started"
        ),
    ):
        sessions.create_session()


def test_create_session() -> None:
    database, sessions = (
        make_memory_runtime()
    )

    session = (
        sessions.create_session()
    )

    value = session.execute(
        text(
            "SELECT 1"
        )
    ).scalar_one()

    assert value == 1

    session.close()

    sessions.stop()
    database.dispose()


# ============================================================
# Transaction handling
# ============================================================


def test_session_scope_commits() -> None:
    database, sessions = (
        make_memory_runtime()
    )

    engine = database.require_engine()

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE test_items (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )
        )

    with sessions.session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO test_items (
                    id,
                    name
                )
                VALUES (
                    1,
                    'Phoenix'
                )
                """
            )
        )

    with sessions.session_scope() as session:
        value = session.execute(
            text(
                """
                SELECT name
                FROM test_items
                WHERE id = 1
                """
            )
        ).scalar_one()

    assert value == "Phoenix"

    sessions.stop()
    database.dispose()


def test_session_scope_rolls_back_on_failure() -> None:
    database, sessions = (
        make_memory_runtime()
    )

    engine = database.require_engine()

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE test_items (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                )
                """
            )
        )

    with pytest.raises(
        RuntimeError,
        match="force rollback",
    ):
        with sessions.session_scope() as session:
            session.execute(
                text(
                    """
                    INSERT INTO test_items (
                        id,
                        name
                    )
                    VALUES (
                        1,
                        'Should Roll Back'
                    )
                    """
                )
            )

            raise RuntimeError(
                "force rollback"
            )

    with sessions.session_scope() as session:
        count = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM test_items
                """
            )
        ).scalar_one()

    assert count == 0

    sessions.stop()
    database.dispose()


def test_multiple_sessions_share_memory_database() -> None:
    database, sessions = (
        make_memory_runtime()
    )

    with sessions.session_scope() as session:
        session.execute(
            text(
                """
                CREATE TABLE shared_test (
                    value INTEGER NOT NULL
                )
                """
            )
        )

        session.execute(
            text(
                """
                INSERT INTO shared_test (
                    value
                )
                VALUES (42)
                """
            )
        )

    with sessions.session_scope() as session:
        value = session.execute(
            text(
                """
                SELECT value
                FROM shared_test
                """
            )
        ).scalar_one()

    assert value == 42

    sessions.stop()
    database.dispose()


def test_session_manager_stop() -> None:
    database, sessions = (
        make_memory_runtime()
    )

    sessions.stop()

    assert sessions.started is False

    with pytest.raises(
        RuntimeError,
        match=(
            "database session manager "
            "has not been started"
        ),
    ):
        sessions.create_session()

    database.dispose()


def test_session_manager_can_restart() -> None:
    database, sessions = (
        make_memory_runtime()
    )

    sessions.stop()

    assert sessions.started is False

    sessions.start()

    assert sessions.started is True

    with sessions.session_scope() as session:
        assert (
            session.execute(
                text("SELECT 1")
            ).scalar_one()
            == 1
        )

    sessions.stop()
    database.dispose()