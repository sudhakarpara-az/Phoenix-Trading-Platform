from typing import cast

from src.app.bootstrap import (
    compose_reporting_end_of_day,
)
from src.app.container import (
    build_persistence_foundation,
    build_reporting_end_of_day,
    build_reporting_foundation,
)
from src.database.engine import (
    DatabaseConfig,
)
from src.notifications.end_of_day_notifications import (
    TradingDayEndOfDayNotificationCoordinator,
)


def test_reporting_eod_reuses_exact_m11_and_m12_instances():
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    try:
        reporting = build_reporting_foundation(
            persistence=persistence
        )

        exact_m11 = cast(
            TradingDayEndOfDayNotificationCoordinator,
            object(),
        )

        coordinator = build_reporting_end_of_day(
            reporting=reporting,
            notification_end_of_day=exact_m11,
        )

        assert coordinator.end_of_day is exact_m11

        assert (
            coordinator.daily_report
            is reporting.daily_report
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()


def test_reporting_eod_bootstrap_preserves_exact_instances():
    persistence = build_persistence_foundation(
        config=DatabaseConfig.sqlite_memory()
    )

    try:
        reporting = build_reporting_foundation(
            persistence=persistence
        )

        exact_m11 = cast(
            TradingDayEndOfDayNotificationCoordinator,
            object(),
        )

        coordinator = compose_reporting_end_of_day(
            reporting=reporting,
            notification_end_of_day=exact_m11,
        )

        assert coordinator.end_of_day is exact_m11

        assert (
            coordinator.daily_report
            is reporting.daily_report
        )

    finally:
        persistence.sessions.stop()
        persistence.database.dispose()
