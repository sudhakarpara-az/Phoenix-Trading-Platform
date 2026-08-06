"""
Phoenix Trading Platform
Configuration Loader
"""

from pathlib import Path
import yaml


class ConfigManager:

    def __init__(self):

        project_root = Path(__file__).resolve().parents[2]

        self.config_path = project_root / "config" / "settings.yaml"

        self.config = self.load()

    def load(self):

        if not self.config_path.exists():

            raise FileNotFoundError(
                f"Configuration file not found:\n{self.config_path}"
            )

        with open(self.config_path, "r", encoding="utf-8") as file:

            return yaml.safe_load(file)

    def get(self, section):

        return self.config.get(section, {})

    def get_value(self, section, key):

        return self.config.get(section, {}).get(key)


config = ConfigManager()