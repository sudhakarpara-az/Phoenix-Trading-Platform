from src.app.bootstrap import (
    compose_reporting_foundation,
)
from src.app.container import (
    PhoenixReportingContainer,
    build_persistence_foundation,
    build_reporting_foundation,
)
from src.database.engine import (
    DatabaseConfig,
)
from src.database.repositories.sqlalchemy_repositories import (
    SQLAlchemyPnLSnapshotRepository,
)


def test_reporting_foundation_reuses_existing_persistence_graph():
    persistence = (
        build_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        reporting = build_reporting_foundation(
            persistence=persistence
        )

        assert isinstance(
            reporting,
            PhoenixReportingContainer,
        )

        assert (
            reporting.persistence
            is persistence
        )

        assert isinstance(
            reporting.pnl_repository,
            SQLAlchemyPnLSnapshotRepository,
        )

        # Existing frozen persistence API has no P&L field.
        # The M12 reader must share the exact same session owner.
        assert (
            getattr(
                reporting.pnl_repository,
                "_sessions",
            )
            is persistence.sessions
        )

        assert (
            getattr(
                reporting.trade_journal,
                "_order_repository",
            )
            is persistence.order_repository
        )

        assert (
            getattr(
                reporting.trade_journal,
                "_order_fill_repository",
            )
            is persistence.order_fill_repository
        )

        assert (
            getattr(
                reporting.trade_journal,
                "_position_repository",
            )
            is persistence.position_repository
        )

        assert (
            reporting.audit_timeline.repository
            is persistence.audit_repository
        )

        assert (
            reporting.runtime_report
            .runtime_repository
            is persistence.runtime_repository
        )

        assert (
            reporting.runtime_report.trade_journal
            is reporting.trade_journal
        )

        assert (
            reporting.runtime_report.trade_analytics
            is reporting.trade_analytics
        )

        assert (
            reporting.runtime_report.audit_timeline
            is reporting.audit_timeline
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_bootstrap_preserves_exact_reporting_container_input():
    persistence = (
        build_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        reporting = (
            compose_reporting_foundation(
                persistence=persistence
            )
        )

        assert (
            reporting.persistence
            is persistence
        )

        assert (
            getattr(
                reporting.pnl_repository,
                "_sessions",
            )
            is persistence.sessions
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()

def test_daily_reporting_uses_same_session_and_runtime_report():
    persistence = (
        build_persistence_foundation(
            config=DatabaseConfig.sqlite_memory()
        )
    )

    try:
        reporting = build_reporting_foundation(
            persistence=persistence
        )

        assert (
            reporting.trading_date_runtime_query.sessions
            is persistence.sessions
        )

        assert (
            reporting.daily_report.runtime_query
            is reporting.trading_date_runtime_query
        )

        assert (
            reporting.daily_report.runtime_report
            is reporting.runtime_report
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
