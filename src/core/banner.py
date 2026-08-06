"""
Phoenix Trading Platform

Banner Module

Displays the application startup banner.
"""

from src.config.config_loader import config


class Banner:
    """Displays the application banner."""

    @staticmethod
    def show() -> None:

        app = config.settings["application"]

        print("\n")
        print("=" * 70)
        print(f"        {app['name']}")
        print("=" * 70)
        print(f"Version      : {app['version']}")
        print(f"Environment  : {app['environment']}")
        print("=" * 70)
        print()


banner = Banner()