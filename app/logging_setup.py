from __future__ import annotations

import logging
import os
from logging import Logger


def configure_logging(level_name: str = "INFO") -> Logger:
    level = getattr(logging, level_name.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt=(
                "%(asctime)s | %(levelname)s | %(name)s | "
                "%(filename)s:%(lineno)d | %(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Reduce noise from third-party loggers
    for noisy in [
        "aiogram",
        "aiohttp.access",
    ]:
        logging.getLogger(noisy).setLevel(os.getenv("NOISY_LOG_LEVEL", "WARNING"))

    return root_logger
