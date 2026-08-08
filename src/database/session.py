"""
Phoenix M08 database session management.

Provides explicit SQLAlchemy transactional boundaries.

Responsibilities:
    - Session factory creation.
    - Transaction commit.
    - Rollback on failure.
    - Session cleanup.
    - Safe runtime lifecycle.

Repositories introduced in M08-T04 will depend on this layer.
"""

from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import (
    Generator,
)

from sqlalchemy.orm import (
    Session,
    sessionmaker,
)

from src.database.engine import (
    DatabaseEngine,
)


class DatabaseSessionManager:
    """
    Phoenix SQLAlchemy session manager.

    One instance is normally associated with one DatabaseEngine.
    """

    def __init__(
        self,
        *,
        database_engine: DatabaseEngine,
    ) -> None:
        self._database_engine = (
            database_engine
        )

        self._session_factory: (
            sessionmaker[Session]
            | None
        ) = None

        self._lock = RLock()

    @property
    def started(
        self,
    ) -> bool:
        with self._lock:
            return (
                self._session_factory
                is not None
            )

    def start(
        self,
    ) -> None:
        """
        Initialize the Session factory.

        Engine startup remains explicitly owned by
        DatabaseEngine.
        """

        with self._lock:
            if (
                self._session_factory
                is not None
            ):
                return

            engine = (
                self._database_engine
                .require_engine()
            )

            self._session_factory = (
                sessionmaker(
                    bind=engine,
                    class_=Session,
                    autoflush=False,
                    expire_on_commit=False,
                )
            )

    def create_session(
        self,
    ) -> Session:
        """
        Create a raw SQLAlchemy Session.

        Prefer session_scope() for normal Phoenix code.
        """

        with self._lock:
            if (
                self._session_factory
                is None
            ):
                raise RuntimeError(
                    "database session manager "
                    "has not been started"
                )

            return self._session_factory()

    @contextmanager
    def session_scope(
        self,
    ) -> Generator[
        Session,
        None,
        None,
    ]:
        """
        Transaction boundary.

        Success:
            commit

        Failure:
            rollback
            re-raise

        Always:
            close session
        """

        session = self.create_session()

        try:
            yield session

            session.commit()

        except Exception:
            session.rollback()
            raise

        finally:
            session.close()

    def stop(
        self,
    ) -> None:
        """
        Stop producing new sessions.

        Existing checked-out sessions remain responsible for
        their own cleanup.
        """

        with self._lock:
            self._session_factory = None