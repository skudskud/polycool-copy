"""
Logging configuration for Polycool Alert Bot
"""

import logging
import sys
from config import LOG_LEVEL, LOG_FORMAT


def setup_logger(name: str = "alert_bot") -> logging.Logger:
    """
    Set up logger with consistent formatting
    
    Args:
        name: Logger name
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Only add handler if not already present
    if not logger.handlers:
        logger.setLevel(getattr(logging, LOG_LEVEL.upper()))
        
        # Console handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, LOG_LEVEL.upper()))
        
        # Formatter
        formatter = logging.Formatter(LOG_FORMAT)
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
    
    return logger


# Create default logger
logger = setup_logger()

