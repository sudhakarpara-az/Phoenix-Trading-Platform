"""
Phoenix Trading Platform

Application Entry Point
"""

from src.app.startup import StartupManager
from src.core.logger import logger


def main() -> None:
    """
    Main application entry point.
    """

    startup = StartupManager()

    if startup.initialize():
        logger.info("Application is ready.")


if __name__ == "__main__":
    main()