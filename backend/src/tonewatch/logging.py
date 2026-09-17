"""Structured logging configuration with request and secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pathlib import Path

request_id: ContextVar[str] = ContextVar("tonewatch_request_id", default="")
_token: ContextVar[str] = ContextVar("tonewatch_api_token", default="")
_SENSITIVE_LOG_WORDS = (
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "token",
    "csrf",
)
_QUERY = re.compile(r"(\S+?)\?[^\s\"]*")
_TOKEN_QUERY = re.compile(r"([?&]t=)[^\s\"&]*")


def _redact_query(value: str) -> str:
    """Remove query strings from request lines and structured log values."""
    return _TOKEN_QUERY.sub(r"\1REDACTED", _QUERY.sub(r"\1", value))


def _redact_value(value: Any, api_token: str) -> Any:
    if isinstance(value, str) and api_token and api_token in value:
        return "[REDACTED]"
    if isinstance(value, str):
        return _redact_query(value)
    if isinstance(value, MutableMapping):
        return {key: _redact_value(item, api_token) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, api_token) for item in value]
    return value


def is_sensitive_log_key(key: object) -> bool:
    """Return whether a log field name should use conservative substring redaction."""
    normalized = str(key).casefold()
    return any(word in normalized for word in _SENSITIVE_LOG_WORDS)


def _redact(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    api_token = _token.get()
    for key in tuple(event_dict):
        if is_sensitive_log_key(key):
            event_dict[key] = "[REDACTED]"
        else:
            event_dict[key] = _redact_value(event_dict[key], api_token)
    return event_dict


class UvicornAccessQueryFilter(logging.Filter):
    """Strip query strings from uvicorn access records before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact query strings in every string argument used by uvicorn."""
        rendered = record.getMessage()
        record.msg = _redact_query(rendered)
        record.args = ()
        return True


def configure_logging(
    level: str,
    *,
    json: bool = True,
    api_token: str = "",
    data_dir: Path | None = None,
) -> None:
    """Route structlog through stdlib logging with UTC timestamps and redaction."""
    _token.set(api_token)
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[structlog.contextvars.merge_contextvars, _redact, timestamper],
    )
    if sys.stderr is not None:
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
    elif data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(data_dir / "tonewatch.log", encoding="utf-8")
    else:
        handler = logging.NullHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(UvicornAccessQueryFilter())
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
