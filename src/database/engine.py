"""
Phoenix M08 database engine infrastructure.

Responsibilities:
    - Database configuration.
    - SQLAlchemy Engine construction.
    - SQLite development database configuration.
    - In-memory SQLite test configuration.
    - Database connectivity/health checks.
    - SQLite foreign-key enforcement.
    - Safe engine disposal.

No Phoenix ORM tables are defined here.
Those belong to M08-T03.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from sqlalchemy import (
    Engine,
    create_engine,
    event,
    text,
)
from sqlalchemy.pool import StaticPool


DEFAULT_DATABASE_PATH = Path(
    "data"
) / "phoenix.db"


@dataclass(
    frozen=True,
    slots=True,
)
class DatabaseConfig:
    """
    Phoenix database-engine configuration.

    Development default:
        SQLite file:
            data/phoenix.db

    Tests may use:
        sqlite+pysqlite:///:memory:
    """

    url: str = (
        "sqlite+pysqlite:///data/phoenix.db"
    )

    echo: bool = False

    create_parent_directory: bool = True

    def __post_init__(
        self,
    ) -> None:
        normalized_url = self.url.strip()

        if not normalized_url:
            raise ValueError(
                "database url cannot be empty"
            )

        if normalized_url != self.url:
            object.__setattr__(
                self,
                "url",
                normalized_url,
            )

    @classmethod
    def sqlite_file(
        cls,
        path: str | Path = DEFAULT_DATABASE_PATH,
        *,
        echo: bool = False,
    ) -> "DatabaseConfig":
        """
        Build SQLite file configuration.
        """

        database_path = Path(
            path
        )

        return cls(
            url=(
                "sqlite+pysqlite:///"
                f"{database_path.as_posix()}"
            ),
            echo=echo,
            create_parent_directory=True,
        )

    @classmethod
    def sqlite_memory(
        cls,
        *,
        echo: bool = False,
    ) -> "DatabaseConfig":
        """
        Build isolated in-memory SQLite configuration.

        StaticPool ensures all sessions created from this
        engine use the same in-memory database connection.
        """

        return cls(
            url="sqlite+pysqlite:///:memory:",
            echo=echo,
            create_parent_directory=False,
        )

    @property
    def is_sqlite(
        self,
    ) -> bool:
        return self.url.startswith(
            "sqlite"
        )

    @property
    def is_memory_sqlite(
        self,
    ) -> bool:
        return (
            self.is_sqlite
            and ":memory:" in self.url
        )

    @property
    def sqlite_path(
        self,
    ) -> Path | None:
        """
        Return the filesystem path for file-backed SQLite.

        Returns None for:
            - in-memory SQLite
            - non-SQLite databases
        """

        if (
            not self.is_sqlite
            or self.is_memory_sqlite
        ):
            return None

        prefix = (
            "sqlite+pysqlite:///"
        )

        if self.url.startswith(
            prefix
        ):
            value = self.url[
                len(prefix):
            ]

            return Path(
                value
            )

        return None


class DatabaseEngine:
    """
    Lifecycle wrapper around SQLAlchemy Engine.

    Engine construction is lazy. Merely importing this module
    never creates data/phoenix.db.
    """

    def __init__(
        self,
        config: DatabaseConfig | None = None,
    ) -> None:
        self._config = (
            config
            or DatabaseConfig.sqlite_file()
        )

        self._engine: Engine | None = None

        self._lock = RLock()

    @property
    def config(
        self,
    ) -> DatabaseConfig:
        return self._config

    @property
    def started(
        self,
    ) -> bool:
        with self._lock:
            return self._engine is not None

    def start(
        self,
    ) -> Engine:
        """
        Create the SQLAlchemy Engine if necessary.

        Calling start repeatedly is idempotent.
        """

        with self._lock:
            if self._engine is not None:
                return self._engine

            self._prepare_filesystem()

            engine_kwargs: dict = {
                "echo": self._config.echo,
                "future": True,
                "pool_pre_ping": True,
            }

            if (
                self._config.is_memory_sqlite
            ):
                engine_kwargs[
                    "connect_args"
                ] = {
                    "check_same_thread": False,
                }

                engine_kwargs[
                    "poolclass"
                ] = StaticPool

            elif self._config.is_sqlite:
                engine_kwargs[
                    "connect_args"
                ] = {
                    "check_same_thread": False,
                }

            engine = create_engine(
                self._config.url,
                **engine_kwargs,
            )

            if self._config.is_sqlite:
                self._configure_sqlite(
                    engine
                )

            self._engine = engine

            return engine

    def require_engine(
        self,
    ) -> Engine:
        """
        Return the active Engine.

        Unlike start(), this method does not implicitly
        initialize persistence.
        """

        with self._lock:
            if self._engine is None:
                raise RuntimeError(
                    "database engine has not been started"
                )

            return self._engine

    def health_check(
        self,
    ) -> bool:
        """
        Perform a minimal round-trip against the database.
        """

        engine = self.require_engine()

        try:
            with engine.connect() as connection:
                value = connection.execute(
                    text("SELECT 1")
                ).scalar_one()

            return value == 1

        except Exception:
            return False

    def dispose(
        self,
    ) -> None:
        """
        Dispose database connections.

        Safe to call repeatedly.
        """

        with self._lock:
            if self._engine is None:
                return

            self._engine.dispose()

            self._engine = None

    def _prepare_filesystem(
        self,
    ) -> None:
        if (
            not self._config
            .create_parent_directory
        ):
            return

        path = self._config.sqlite_path

        if path is None:
            return

        parent = path.parent

        if (
            parent
            and parent != Path(".")
        ):
            parent.mkdir(
                parents=True,
                exist_ok=True,
            )

    @staticmethod
    def _configure_sqlite(
        engine: Engine,
    ) -> None:
        """
        Enable SQLite foreign-key enforcement for every DBAPI
        connection.

        M08-T03 will depend on foreign keys for relational
        integrity.
        """

        @event.listens_for(
            engine,
            "connect",
        )
        def _set_sqlite_pragma(
            dbapi_connection,
            connection_record,
        ) -> None:
            del connection_record

            cursor = (
                dbapi_connection.cursor()
            )

            try:
                cursor.execute(
                    "PRAGMA foreign_keys=ON"
                )

                cursor.execute(
                    "PRAGMA busy_timeout=5000"
                )

            finally:
                cursor.close()