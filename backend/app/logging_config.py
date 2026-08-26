"""
Minimal structured logging — no external dependency (no structlog), just a
consistent config plus a dedicated logger for auditing security decisions
(guardrails), which must stay traceable even in prod. See
docs/security-model.md.
"""
from __future__ import annotations

import logging
import os

AUDIT_LOGGER_NAME = "aegis.audit"


def configure_logging() -> None:
    level_name = os.getenv("AEGIS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # uvicorn already configures its own access loggers — no need to touch those.
    logging.getLogger(AUDIT_LOGGER_NAME).setLevel(logging.INFO)


def get_audit_logger() -> logging.Logger:
    return logging.getLogger(AUDIT_LOGGER_NAME)
