"""
Phoenix Trading Platform

Logger Module

Provides centralized logging for the application.
"""

from pathlib import Path
from loguru import logger

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Log directory
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Log file
LOG_FILE = LOG_DIR / "phoenix.log"

# Remove default logger
logger.remove()

# Console Logger
logger.add(
    sink=lambda message: print(message, end=""),
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
           "<level>{level: <8}</level> | "
           "{message}",
)

# File Logger
logger.add(
    LOG_FILE,
    level="DEBUG",
    rotation="10 MB",
    retention="30 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

__all__ = ["logger"]