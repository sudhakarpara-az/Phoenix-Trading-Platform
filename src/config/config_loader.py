"""
Phoenix Trading Platform

Configuration Loader

This module loads all application configuration files.
"""

from pathlib import Path
import json
import yaml


class ConfigLoader:
    """
    Loads YAML and JSON configuration files.
    """

    def __init__(self):

        self.project_root = Path(__file__).resolve().parents[2]

        self.config_path = self.project_root / "config"

        self.settings = {}
        self.strategy = {}
        self.logging = {}
        self.symbols = {}

    def load_yaml(self, filename: str):

        file_path = self.config_path / filename

        if not file_path.exists():
            raise FileNotFoundError(f"{filename} not found")

        with open(file_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file)

    def load_json(self, filename: str):

        file_path = self.config_path / filename

        if not file_path.exists():
            raise FileNotFoundError(f"{filename} not found")

        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def load(self):

        self.settings = self.load_yaml("settings.yaml")
        self.strategy = self.load_yaml("strategy.yaml")
        self.logging = self.load_yaml("logging.yaml")
        self.symbols = self.load_json("symbols.json")

        return self


config = ConfigLoader().load()