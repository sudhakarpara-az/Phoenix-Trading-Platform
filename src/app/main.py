"""
Phoenix Trading Platform

Application Entry Point
"""

from __future__ import annotations

from datetime import datetime

from src.app.container import (
    PhoenixRuntimeStartupContainer,
)
from src.app.startup import (
    ApplicationStartupError,
    StartupManager,
)
from src.core.logger import logger
from src.services.scheduler import (
    TradingDayStartupResult,
)


def start_composed_runtime(
    *,
    runtime_startup:
        PhoenixRuntimeStartupContainer,
    started_at: datetime,
    recovery_checked_at:
        datetime | None = None,
    running_at:
        datetime | None = None,
) -> TradingDayStartupResult:
    """
    Validate Phoenix, then start an already-composed runtime.

    Dependency construction remains in container/bootstrap.
    This entry point deliberately does not construct Dhan,
    market-data, strategy, risk, or persistence objects.
    """

    startup = StartupManager()

    if not startup.initialize():
        raise ApplicationStartupError(
            "Phoenix startup validation failed"
        )

    return startup.start_runtime(
        runtime_startup=runtime_startup,
        started_at=started_at,
        recovery_checked_at=(
            recovery_checked_at
        ),
        running_at=running_at,
    )


def main() -> None:
    """
    Validate the Phoenix application shell.

    Production deployment code must compose the required runtime
    dependencies through src.app.bootstrap/container, then call
    start_composed_runtime() with that exact graph.
    """

    startup = StartupManager()

    if startup.initialize():
        logger.info(
            "Application validation complete."
        )


if __name__ == "__main__":
    main()


__all__ = [
    "main",
    "start_composed_runtime",
]
