"""Structured JSON logging with secret masking."""
import logging
import re

import structlog

# Anything that looks like a credential value gets masked before it hits a sink.
_SECRET_KEY_RE = re.compile(r"(token|secret|password|api[_-]?key|authorization)", re.I)


def _mask_secrets(_logger, _method, event_dict: dict) -> dict:
    for k in list(event_dict):
        if _SECRET_KEY_RE.search(str(k)):
            event_dict[k] = "***MASKED***"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _mask_secrets,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
    )


def get_logger(name: str):
    return structlog.get_logger(name)
