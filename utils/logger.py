"""
Logging Configuration
Structured async logging with optional Telegram log channel support
"""
import logging
import sys
from config import LOG_LEVEL


def setup_logging():
    """Configure root logger with console handler."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=date_fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Silence noisy libraries
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized at level {LOG_LEVEL}")
    return logger
