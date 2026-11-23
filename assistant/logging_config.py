"""Logging setup: file + console for diagnosing issues."""
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from . import config

LOG_PATH = config.HOME / "assistant.log"
_LOG_LINE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ \[(?P<level>\w+)\] (?P<name>[\w.]+): (?P<msg>.*)$")


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


def recent_errors(since: datetime, limit: int = 5) -> list:
    """ERROR-level log messages written after `since`, oldest first - for a quick, self-diagnosed
    'this went wrong while you were away' summary instead of errors only existing silently in a file."""
    if not LOG_PATH.exists():
        return []
    out = []
    try:
        with open(LOG_PATH, errors="replace") as f:
            for line in f:
                m = _LOG_LINE.match(line)
                if not m or m["level"] != "ERROR":
                    continue
                try:
                    ts = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if ts > since:
                    out.append(m["msg"])
    except OSError:
        return []
    return out[-limit:]
