"""
Phoenix Trading Platform

Startup Manager
"""

from src.core.banner import banner
from src.core.logger import logger
from src.config.validator import validator
from src.config.env_loader import env
from src.config.config_loader import config


class StartupManager:
    """
    Handles Phoenix application startup.
    """

    def initialize(self) -> bool:
        """
        Initialize the application.
        """

        # Display startup banner
        banner.show()

        logger.info("Starting Phoenix Trading Platform...")

        # Validate project structure
        validator.validate()
        logger.success("Startup validation completed.")

        # Load environment
        logger.success(f"Environment: {env.app_env}")

        # Verify configuration loaded
        logger.success(
            f"Configuration loaded: {config.settings['application']['name']}"
        )

        logger.success("Phoenix initialized successfully.")

        return True