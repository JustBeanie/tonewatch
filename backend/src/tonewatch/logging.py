"""Structured logging configuration with request and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import deque
from collections.abc import MutableMapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pathlib import Path

request_id: ContextVar[str] = ContextVar("tonewatch_request_id", default="")
_token: ContextVar[str] = ContextVar("tonewatch_api_token", default="")


@dataclass
class SecretHolder:
    """Mutable live credentials used by log redaction."""

    current: str = ""
    previous: str | None = None


_token_holder: ContextVar[SecretHolder | None] = ContextVar(
    "tonewatch_api_token_holder", default=None
)
_active_ring: list[LogRing | None] = [None]
_SENSITIVE_LOG_WORDS = (
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "token",
    "csrf",
    "psk",
    "private_key",
    "api_key",
)
_QUERY = re.compile(r"(\S+?)\?[^\s\"]*")
_TOKEN_QUERY = re.compile(r"([?&]t=)[^\s\"&]*")


def _redact_query(value: str) -> str:
    """Remove query strings from request lines and structured log values."""
    if "?" not in value:
        return value
    return _TOKEN_QUERY.sub(r"\1REDACTED", _QUERY.sub(r"\1", value))


def _redact_value(value: Any, api_token: str | SecretHolder) -> Any:
    tokens = (
        (api_token.current, api_token.previous)
        if isinstance(api_token, SecretHolder)
        else (api_token, None)
    )
    if isinstance(value, str) and any(token and token in value for token in tokens):
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
    api_token = _token_holder.get() or _token.get()
    for key in tuple(event_dict):
        if is_sensitive_log_key(key):
            event_dict[key] = "[REDACTED]"
        else:
            event_dict[key] = _redact_value(event_dict[key], api_token)
    return event_dict


class LogRing:
    """Bounded store of rendered, already-redacted structured log records."""

    def __init__(self, max_records: int = 2000, max_record_bytes: int = 16 * 1024) -> None:
        """Create a record-count and rendered-byte bounded ring."""
        self.max_record_bytes = max(1024, max_record_bytes)
        self._records: deque[dict[str, Any]] = deque(maxlen=max(1, max_records))
        self._next_seq = 1

    def append_rendered(self, rendered: str, logger: str = "") -> None:
        """Append one rendered JSON record, ignoring malformed or oversized failures."""
        try:
            record = json.loads(rendered)
            if not isinstance(record, dict):
                return
            encoded = rendered.encode("utf-8")
            if len(encoded) > self.max_record_bytes:
                strings = [key for key, value in record.items() if isinstance(value, str)]
                key = max(strings, key=lambda item: len(str(record[item]))) if strings else "event"
                budget = max(32, self.max_record_bytes // 3)
                record[key] = (
                    str(record.get(key, "")).encode("utf-8")[:budget].decode("utf-8", "ignore")
                )
                record["truncated"] = True
                record["truncated_bytes"] = len(encoded) - len(json.dumps(record).encode("utf-8"))
            record.setdefault("time", record.get("timestamp", ""))
            record["seq"] = self._next_seq
            self._next_seq += 1
            record["level"] = str(record.get("level", "info")).casefold()
            record["logger"] = str(record.get("logger", "") or logger)[:200]
            record["event"] = str(record.get("event", ""))[:2000]
            required = {
                "seq",
                "time",
                "timestamp",
                "level",
                "logger",
                "event",
                "truncated",
                "truncated_bytes",
            }
            for key in list(record)[32:]:
                if key not in required:
                    del record[key]
            self._records.append(record)
        except Exception:
            return

    def records(
        self, *, level: str | None = None, since_seq: int | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Return a bounded filtered snapshot for API or bundle consumers."""
        level_name = (level or "NOTSET").upper()
        levels = logging.getLevelNamesMapping()
        if level_name not in levels:
            raise ValueError("unknown log level")  # noqa: TRY003 -- concise API validation error.
        minimum = levels[level_name]
        record_levels = logging.getLevelNamesMapping()
        result = []
        for item in self._records:
            if record_levels.get(str(item.get("level", "info")).upper(), logging.INFO) < minimum:
                continue
            if since_seq is not None and int(item.get("seq", 0)) <= since_seq:
                continue
            result.append(dict(item))
        return result[-max(1, limit) :]


def active_log_ring() -> LogRing | None:
    """Return the ring installed by the current application logging setup."""
    return _active_ring[0]


class LogRingHandler(logging.FileHandler):
    """Handler whose failures are deliberately isolated from application logging."""

    def __init__(self, ring: LogRing, *, stream: Any = None, filename: Path | None = None) -> None:
        """Create the single root sink and ring capture handler."""
        if filename is not None:
            super().__init__(filename, encoding="utf-8")
            self._owns_stream = True
        else:
            logging.Handler.__init__(self)
            self.stream = stream
            self._owns_stream = False
        self.ring = ring

    def emit(self, record: logging.LogRecord) -> None:
        """Render and append without allowing failures to escape logging."""
        try:
            rendered = self.format(record)
            self.ring.append_rendered(rendered, record.name)
            if self.stream is not None:
                self.stream.write(rendered + self.terminator)
                self.flush()
        except Exception:
            return

    def close(self) -> None:
        """Close only a file stream owned by this handler."""
        if self._owns_stream:
            super().close()
        else:
            logging.Handler.close(self)


class UvicornAccessQueryFilter(logging.Filter):
    """Strip query strings from uvicorn access records before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact query strings in every string argument used by uvicorn."""
        rendered = record.getMessage()
        record.msg = _redact_query(rendered)
        record.args = ()
        return True


class RenderSizeFilter(logging.Filter):
    """Keep pathological structured fields bounded before any sink formats them."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Truncate large structured string fields before formatting."""
        try:
            if isinstance(record.msg, dict):
                for key, value in list(record.msg.items()):
                    if isinstance(value, str) and len(value.encode("utf-8")) > 16 * 1024:
                        record.msg[key] = value.encode("utf-8")[: 16 * 1024].decode(
                            "utf-8", "ignore"
                        )
                        record.msg["truncated"] = True
        except Exception:
            return True
        return True


def configure_logging(  # noqa: PLR0913 -- logging configuration keeps explicit runtime seams.
    level: str,
    *,
    json: bool = True,
    api_token: str = "",
    token_holder: SecretHolder | None = None,
    data_dir: Path | None = None,
    ring: LogRing | None = None,
) -> LogRing:
    """Route structlog through stdlib logging with UTC timestamps and redaction."""
    _token.set(api_token)
    _token_holder.set(token_holder or SecretHolder(api_token))
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[structlog.contextvars.merge_contextvars, _redact, timestamper],
    )
    filename: Path | None = None
    if sys.stderr is not None:
        stream: Any = sys.stderr
    elif data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        stream = None
        filename = data_dir / "tonewatch.log"
    else:
        stream = None
    ring = ring or LogRing()
    _active_ring[0] = ring
    handler = LogRingHandler(ring, stream=stream, filename=filename)
    handler.setFormatter(formatter)
    handler.addFilter(RenderSizeFilter())
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
    return ring


def set_request_id(value: str) -> Any:
    """Bind a request id to the current async context."""
    return structlog.contextvars.bind_contextvars(request_id=value)


def clear_request_id(tokens: Any) -> None:
    """Restore the previous request context."""
    structlog.contextvars.reset_contextvars(**tokens)
