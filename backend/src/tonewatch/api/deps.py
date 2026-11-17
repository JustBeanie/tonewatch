"""Shared request dependencies and configuration operations for API routers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import HTTPException, Request
from pydantic import ValidationError

from tonewatch.api.audit import SecretRestoreError, mask_secrets, record_audit, restore_secrets
from tonewatch.config.history import ConfigHistory, HistoryError
from tonewatch.config.models import AppConfig
from tonewatch.config.store import ConfigConflictError, replace_config

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_logger = structlog.get_logger("tonewatch.config")
_python_logger = logging.getLogger("tonewatch.config")


def _dump(value: Any) -> Any:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return mask_secrets(raw)


def authenticated(request: Request) -> None:
    """Require any supported authentication method."""
    request.state.auth = request.app.state.auth.authorize(request)


def write_auth(request: Request) -> None:
    """Require authentication and CSRF for cookie state changes."""
    request.state.auth = request.app.state.auth.authorize(request, state_changing=True)


async def config_write(request: Request) -> AsyncIterator[None]:
    """Keep read-modify-write handlers and their runtime reloads in order."""
    write_auth(request)
    async with request.app.state.config_write_lock:
        yield


def credential_write_auth(request: Request) -> None:
    """Require write auth, and require CSRF-capable auth for credential changes."""
    write_auth(request)
    if request.state.auth == "ingress":
        raise HTTPException(403, "credential changes require bearer or CSRF-protected session auth")


def collection(request: Request, kind: str) -> list[Any]:
    return list(getattr(request.app.state.config, kind))


async def save_config(request: Request, config: AppConfig, *, audit: bool = True) -> AppConfig:
    task = asyncio.create_task(_save_config(request, config, audit=audit))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Keep the request's write lock until an in-progress disk write and reload finish.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                _python_logger.exception("configuration write failed after request cancellation")
        if not task.cancelled():
            task.exception()
        raise


async def _save_config(request: Request, config: AppConfig, *, audit: bool) -> AppConfig:
    before = request.app.state.config
    expected_etag = request.headers.get("if-match")
    try:
        raw_config = config.model_dump(mode="python") if hasattr(config, "model_dump") else config
        config = AppConfig.model_validate(
            restore_secrets(before.model_dump(mode="python"), raw_config)
        )
    except SecretRestoreError as exc:
        raise HTTPException(422, str(exc)) from None
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        if hasattr(request.app.state.store, "save_async"):
            revision = await request.app.state.store.save_async(config, expected_etag=expected_etag)
        else:
            request.app.state.store.save(config)
            revision = request.app.state.store.etag()
    except ConfigConflictError as exc:
        raise HTTPException(412, str(exc)) from None
    request.app.state.config = config
    request.app.state.config_etag = revision
    live = config.live_stream
    live_hub = getattr(request.app.state, "live_hub", None)
    if live_hub is not None:
        live_hub.configure(
            bitrate_kbps=live.bitrate_kbps,
            queue_seconds=2.0,
            max_lag_s=live.max_lag_s,
        )
    await request.app.state.supervisor.reload(config)
    history_recorded = True
    try:
        ConfigHistory(request.app.state.settings.data_dir).record(
            config,
            actor=getattr(request.state, "auth", "unknown"),
            route=getattr(getattr(request, "url", None), "path", "unknown"),
        )
    except HistoryError as exc:
        history_recorded = False
        _logger.warning("configuration history unavailable", error=str(exc))
        _python_logger.warning("configuration history unavailable: %s", exc)
    if audit:
        await record_audit(
            request.app.state.session_factory,
            actor=getattr(request.state, "auth", "unknown"),
            event_type="config_change",
            resource="config",
            before=before.model_dump(mode="json"),
            after=config.model_dump(mode="json"),
            details={"history_recorded": history_recorded},
        )
    return config


async def put(request: Request, kind: str, item: Any) -> AppConfig:
    items = [value for value in collection(request, kind) if value.id != item.id]
    items.append(item)
    try:
        config = replace_config(request.app.state.config, **{kind: items})
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    return await save_config(request, config)


def base_path(request: Request) -> str:
    path = request.headers.get("x-ingress-path", "") if request.state.auth == "ingress" else ""
    return "/" + path.strip("/") if path.strip("/") else ""
