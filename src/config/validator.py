"""
Phoenix Trading Platform

Startup Validator
"""

from pathlib import Path


class StartupValidator:
    """
    Validates that all required files and folders exist
    before the application starts.
    """

    def __init__(self):

        self.project_root = Path(__file__).resolve().parents[2]

    def validate(self):

        required_files = [
            "config/settings.yaml",
            "config/strategy.yaml",
            "config/logging.yaml",
            "config/symbols.json",
            ".env",
        ]

        required_directories = [
            "logs",
        ]

        # Check files
        for file in required_files:

            path = self.project_root / file

            if not path.exists():
                raise FileNotFoundError(f"Missing required file: {file}")

        # Check directories
        for directory in required_directories:

            path = self.project_root / directory

            if not path.exists():
                raise FileNotFoundError(f"Missing required directory: {directory}")

        return True


validator = StartupValidator()