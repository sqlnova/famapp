"""FamApp entry point – starts the FastAPI server."""
from __future__ import annotations

import logging
import os
import sys

import structlog
import uvicorn

from core.config import get_settings


def configure_logging(log_level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if log_level == "DEBUG" else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


if __name__ == "__main__":
    s = get_settings()
    configure_logging(s.log_level)

    logger = structlog.get_logger(__name__)

    # Railway (and most PaaS) inject PORT via environment variable
    port = int(os.environ.get("PORT", 8000))

    logger.info("famapp_starting", env=s.app_env, port=port, log_level=s.log_level)

    uvicorn.run(
        "server.webhook:app",
        host="0.0.0.0",
        port=port,
        reload=not s.is_production,
        log_level=s.log_level.lower(),
    )
