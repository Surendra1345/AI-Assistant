"""Logging setup: file + console for diagnosing issues."""
import logging
import sys
from pathlib import Path

from . import config

LOG_PATH = config.HOME / "assistant.log"


def setup():
    """Configure logging to file and console."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # File handler: everything
    try:
        config.HOME.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(LOG_PATH)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logger.addHandler(fh)
    except Exception as e:
        print(f"Warning: could not set up log file: {e}")
    
    # Console: warnings and errors only
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)
    
    return logger


def get(name: str) -> logging.Logger:
    """Get a logger for a module."""
    return logging.getLogger(name)
