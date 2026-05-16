"""Application logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import LoggingConfig


def configure_logging(config: LoggingConfig) -> logging.Logger:
    """Configure console and rotating file logging for the application."""

    log_level = getattr(logging, config.level.upper(), logging.INFO)
    config.file_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        config.file_path,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    return logging.getLogger("app")


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for application modules."""

    return logging.getLogger(name)
