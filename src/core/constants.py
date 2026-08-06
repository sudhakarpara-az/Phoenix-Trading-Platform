"""
Phoenix Trading Platform

Application Constants
"""

from pathlib import Path


# Project Information
APP_NAME = "Phoenix Trading Platform"
APP_VERSION = "1.0.0"

# Environment
ENV_DEVELOPMENT = "development"
ENV_PRODUCTION = "production"

# Project Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = PROJECT_ROOT / "config"
LOG_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"

# Log Levels
LOG_INFO = "INFO"
LOG_WARNING = "WARNING"
LOG_ERROR = "ERROR"

# Trading Modes
MODE_PAPER = "paper"
MODE_LIVE = "live"