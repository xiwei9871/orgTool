"""Logging bootstrap helpers."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_file_logger(name: str, log_file: Path) -> logging.Logger:
    """Create or reuse a file-backed logger."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_file
        for handler in logger.handlers
    ):
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        logger.addHandler(handler)

    return logger
