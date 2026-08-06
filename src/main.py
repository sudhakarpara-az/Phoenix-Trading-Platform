"""
===========================================================
Phoenix Trading Platform
===========================================================
"""

from core.config import config
from core.logger import logger


def banner():

    print("\n")

    print("=" * 60)

    print("          PHOENIX TRADING PLATFORM")

    print("=" * 60)

    print(
        f"Application : {config.get_value('application','name')}"
    )

    print(
        f"Version     : {config.get_value('application','version')}"
    )

    print(
        f"Environment : {config.get_value('application','environment')}"
    )

    print("=" * 60)


def startup():

    logger.info("Loading configuration...")

    logger.success("Configuration Loaded")

    logger.info("Initializing Logger...")

    logger.success("Logger Started")

    logger.info("Environment Ready")

    logger.success("Phoenix Started Successfully")


def main():

    banner()

    startup()


if __name__ == "__main__":

    main()