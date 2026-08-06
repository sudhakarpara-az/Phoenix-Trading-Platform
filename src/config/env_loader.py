"""
Phoenix Trading Platform

Environment Loader
"""

from pathlib import Path

from dotenv import load_dotenv

import os


class EnvironmentLoader:
    """
    Loads environment variables from the .env file.
    """

    def __init__(self):

        self.project_root = Path(__file__).resolve().parents[2]

        self.env_path = self.project_root / ".env"

        load_dotenv(self.env_path)

    @property
    def app_env(self) -> str:
        return os.getenv("APP_ENV", "development")

    @property
    def dhan_client_id(self) -> str:
        return os.getenv("DHAN_CLIENT_ID", "")

    @property
    def dhan_access_token(self) -> str:
        return os.getenv("DHAN_ACCESS_TOKEN", "")

    @property
    def telegram_bot_token(self) -> str:
        return os.getenv("TELEGRAM_BOT_TOKEN", "")

    @property
    def telegram_chat_id(self) -> str:
        return os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def database_name(self) -> str:
        return os.getenv("DATABASE_NAME", "phoenix.db")


env = EnvironmentLoader()