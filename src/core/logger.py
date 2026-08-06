"""
Phoenix Trading Platform
Logger
"""

from pathlib import Path
from loguru import logger

project_root = Path(__file__).resolve().parents[2]

log_folder = project_root / "logs"

log_folder.mkdir(exist_ok=True)

log_file = log_folder / "phoenix.log"

logger.remove()

logger.add(
    log_file,
    rotation="10 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

logger.add(
    lambda msg: print(msg, end=""),
    level="INFO",
)

__all__ = ["logger"]