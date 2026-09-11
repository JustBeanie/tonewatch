"""Structured logging configuration with request and secret redaction."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

request_id: ContextVar[str] = ContextVar("tonewatch_request_id", default="")
_token: ContextVar[str] = ContextVar("tonewatch_api_token", default="")
_SENSITIVE = ("authorization", "cookie", "set-cookie", "password", "token", "csrf")


def _redact_value(value: Any, api_token: str) -> Any:
    if isinstance(value, str) and api_token and api_token in value:
        return "[REDACTED]"
    if isinstance(value, MutableMapping):
        return {key: _redact_value(item, api_token) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, api_token) for item in value]
    return value


def _redact(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    api_token = _token.get()
    for key in tuple(event_dict):
        if any(word in key.casefold() for word in _SENSITIVE):
            event_dict[key] = "[REDACTED]"
        else:
            event_dict[key] = _redact_value(event_dict[key], api_token)
    return event_dict


def configure_logging(level: str, *, json: bool = True, api_token: str = "") -> None:
    """Route structlog through stdlib logging with UTC timestamps and redaction."""
    _token.set(api_token)
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[structlog.contextvars.merge_contextvars, _redact, timestamper],
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _redact,
            structlog.processors.add_log_level,
            timestamper,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def set_request_id(value: str) -> Any:
    """Bind a request id to the current async context."""
    return structlog.contextvars.bind_contextvars(request_id=value)


def clear_request_id(tokens: Any) -> None:
    """Restore the previous request context."""
    structlog.contextvars.reset_contextvars(**tokens)
