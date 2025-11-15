"""
Logging configuration for Polycool
"""
import logging
import sys
import time
from collections import defaultdict
from typing import Optional

from infrastructure.config.settings import settings


class DeduplicationFilter(logging.Filter):
    """Filter to prevent repetitive log messages from cluttering the logs"""

    def __init__(self, max_age: int = 60, max_count: int = 3):
        super().__init__()
        self.max_age = max_age  # seconds
        self.max_count = max_count
        self.message_cache = defaultdict(list)

    def filter(self, record):
        # Skip deduplication for WARNING and above
        if record.levelno >= logging.WARNING:
            return True

        message_key = f"{record.levelname}:{record.getMessage()}"
        current_time = time.time()

        # Clean old entries
        self.message_cache[message_key] = [
            timestamp for timestamp in self.message_cache[message_key]
            if current_time - timestamp < self.max_age
        ]

        # Check if we've seen this message too many times recently
        if len(self.message_cache[message_key]) >= self.max_count:
            return False

        # Add current timestamp
        self.message_cache[message_key].append(current_time)
        return True


def setup_logging(
    name: str = "polycool",
    level: Optional[str] = None,
    format_string: Optional[str] = None,
    enable_deduplication: bool = True,
) -> logging.Logger:
    """
    Setup structured logging for the application

    Args:
        name: Logger name
        level: Logging level (overrides settings)
        format_string: Log format (overrides settings)
        enable_deduplication: Whether to enable log deduplication

    Returns:
        Configured logger instance
    """
    # Use settings if not provided
    log_level = level or settings.logging.level
    log_format = format_string or settings.logging.format

    # Convert string level to logging level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        stream=sys.stdout,
    )

    # Reduce noise from external libraries
    _configure_external_loggers()

    # Create logger
    logger = logging.getLogger(name)

    # Set level
    logger.setLevel(numeric_level)

    # Remove any existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)

    # Add deduplication filter to reduce repetitive messages
    if enable_deduplication:
        dedup_filter = DeduplicationFilter(max_age=60, max_count=3)
        console_handler.addFilter(dedup_filter)

    # Create formatter
    formatter = logging.Formatter(log_format)
    console_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(console_handler)

    # Prevent duplicate messages
    logger.propagate = False

    return logger


def _configure_external_loggers():
    """Configure logging levels for external libraries to reduce noise"""

    # SQLAlchemy - reduce to WARNING to hide all the query logs
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)

    # httpx - reduce HTTP request logs to WARNING
    logging.getLogger('httpx').setLevel(logging.WARNING)

    # Web3 - reduce to WARNING to hide pkg_resources warnings
    logging.getLogger('web3').setLevel(logging.WARNING)

    # APScheduler - reduce to WARNING to hide scheduling logs
    logging.getLogger('apscheduler').setLevel(logging.WARNING)

    # Redis pubsub - reduce connection logs
    logging.getLogger('redis').setLevel(logging.WARNING)

    # Other potentially noisy libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
