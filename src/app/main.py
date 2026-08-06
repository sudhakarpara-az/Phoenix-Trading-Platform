"""
Phoenix Trading Platform

Application Entry Point
"""

from src.core.banner import banner
from src.core.logger import logger
from src.config.config_loader import config


class PhoenixApplication:
    """
    Main Phoenix Trading Platform Application
    """

    def __init__(self):
        self.config = config

    def startup(self) -> None:
        """
        Start the application.
        """

        # Display Banner
        banner.show()

        logger.info("Starting Phoenix Trading Platform...")

        logger.success("Configuration Loaded Successfully")

        logger.success("Logger Initialized Successfully")

        logger.success("Phoenix Trading Platform Started Successfully")

        logger.info("System is ready.")

    def run(self) -> None:
        """
        Run the application.
        """

        self.startup()


def main() -> None:
    """
    Application Entry Point
    """

    app = PhoenixApplication()
    app.run()


if __name__ == "__main__":
    main()