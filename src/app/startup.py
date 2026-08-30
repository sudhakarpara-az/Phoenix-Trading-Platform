"""
Phoenix Trading Platform

Startup Manager
"""

from __future__ import annotations

from datetime import datetime

from src.app.container import (
    PhoenixRuntimeStartupContainer,
)
from src.app.recovery import (
    RecoveryStateRestorerBinding,
)
from src.config.config_loader import config
from src.config.env_loader import env
from src.config.validator import validator
from src.core.banner import banner
from src.core.logger import logger
from src.runtime.runtime_types import (
    RuntimeState,
)
from src.services.scheduler import (
    TradingDayStartupResult,
)


class ApplicationStartupError(
    RuntimeError
):
    """
    Phoenix application startup could not proceed safely.
    """


class StartupManager:
    """
    Handles Phoenix application startup.

    M01 responsibilities:
        - banner,
        - project validation,
        - environment/config validation.

    M10 responsibilities:
        - delegate the already-composed runtime graph to the
          exact TradingDayStartupCoordinator,
        - never bypass required recovery,
        - never construct duplicate runtime dependencies.
    """

    def initialize(
        self,
    ) -> bool:
        """
        Initialize and validate the application shell.

        This preserves the existing M01 startup contract.
        """

        banner.show()

        logger.info(
            "Starting Phoenix Trading Platform..."
        )

        validator.validate()

        logger.success(
            "Startup validation completed."
        )

        logger.success(
            f"Environment: {env.app_env}"
        )

        logger.success(
            "Configuration loaded: "
            f"{config.settings['application']['name']}"
        )

        logger.success(
            "Phoenix initialized successfully."
        )

        return True

    def start_runtime(
        self,
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
        Start one already-composed Phoenix trading runtime.

        Ownership remains:

            TradingDayStartupCoordinator
                ->
            TradingRuntimeOrchestrator
                ->
            StartupRecoveryService

        Recovery-required startup is blocked until a deferred
        RecoveryStateRestorerBinding has been bound to the
        concrete production restorer.
        """

        if type(started_at) is not datetime:
            raise TypeError(
                "started_at must be a datetime"
            )

        if (
            recovery_checked_at is not None
            and type(recovery_checked_at)
            is not datetime
        ):
            raise TypeError(
                "recovery_checked_at must be "
                "a datetime or None"
            )

        if (
            running_at is not None
            and type(running_at)
            is not datetime
        ):
            raise TypeError(
                "running_at must be "
                "a datetime or None"
            )

        recovery_plan = (
            runtime_startup.recovery_plan
        )

        state_restorer = (
            runtime_startup
            .recovery_service
            .state_restorer
        )

        if (
            recovery_plan.recovery_required
            and isinstance(
                state_restorer,
                RecoveryStateRestorerBinding,
            )
            and not state_restorer.is_bound
        ):
            raise ApplicationStartupError(
                "recovery-required startup cannot "
                "begin before the production state "
                "restorer is bound"
            )

        health_supervisor = getattr(
            runtime_startup,
            "health_supervisor",
            None,
        )

        if health_supervisor is None:
            result = (
                runtime_startup
                .startup_coordinator
                .start(
                    orchestrator=(
                        runtime_startup
                        .orchestrator
                    ),
                    recovery_plan=(
                        recovery_plan
                    ),
                    started_at=started_at,
                    recovery_checked_at=(
                        recovery_checked_at
                    ),
                    running_at=(
                        running_at
                    ),
                )
            )

        else:
            result = (
                runtime_startup
                .startup_coordinator
                .start(
                    orchestrator=(
                        runtime_startup
                        .orchestrator
                    ),
                    recovery_plan=(
                        recovery_plan
                    ),
                    started_at=started_at,
                    recovery_checked_at=(
                        recovery_checked_at
                    ),
                    running_at=(
                        running_at
                    ),
                    health_supervisor=(
                        health_supervisor
                    ),
                )
            )

        runtime_state = (
            result.runtime.state
        )

        if (
            runtime_state
            is RuntimeState.RUNNING
        ):
            logger.success(
                "Phoenix trading runtime is RUNNING."
            )

        elif (
            runtime_state
            is RuntimeState.FAILED
        ):
            logger.error(
                "Phoenix trading runtime startup "
                "failed closed."
            )

        else:
            logger.info(
                "Phoenix runtime startup completed "
                f"in state {runtime_state.value}."
            )

        return result


__all__ = [
    "ApplicationStartupError",
    "StartupManager",
]