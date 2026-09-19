"""structlog setup, called once on startup.

Console renderer for a developer's terminal, JSON for anything a log
collector will read. Configured in one place so the API and the worker
produce the same shape of log line.
"""

from __future__ import annotations

import logging
import sys

import structlog

from leka.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Point stdlib logging and structlog at the same pipeline."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        cache_logger_on_first_use=True,
    )
