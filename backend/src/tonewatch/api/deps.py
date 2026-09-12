"""Shared request dependencies and configuration operations for API routers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from pydantic import ValidationError

from tonewatch.api.audit import mask_secrets, record_audit
from tonewatch.config.models import AppConfig
from tonewatch.config.store import ConfigConflictError


def _dump(value: Any) -> Any:
    raw = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return mask_secrets(raw)


def authenticated(request: Request) -> None:
    """Require any supported authentication method."""
    request.state.auth = request.app.state.auth.authorize(request)


def write_auth(request: Request) -> None:
    """Require authentication and CSRF for cookie state changes."""
    request.state.auth = request.app.state.auth.authorize(request, state_changing=True)


def collection(request: Request, kind: str) -> list[Any]:
    return list(getattr(request.app.state.config, kind))


async def save_config(request: Request, config: AppConfig, *, audit: bool = True) -> AppConfig:
    before = request.app.state.config
    expected_etag = request.headers.get("if-match")
    try:
        config = AppConfig.model_validate(config)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        if hasattr(request.app.state.store, "save_async"):
            await request.app.state.store.save_async(config, expected_etag=expected_etag)
        else:
            request.app.state.store.save(config)
    except ConfigConflictError as exc:
        raise HTTPException(412, str(exc)) from None
    request.app.state.config = config
    await request.app.state.supervisor.reload(config)
    if audit:
        await record_audit(
            request.app.state.session_factory,
            actor=getattr(request.state, "auth", "unknown"),
            event_type="config_change",
            resource="config",
            before=before.model_dump(mode="json"),
            after=config.model_dump(mode="json"),
        )
    return config


async def put(request: Request, kind: str, item: Any) -> AppConfig:
    items = [value for value in collection(request, kind) if value.id != item.id]
    items.append(item)
    try:
        config = AppConfig(
            tone_sets=items if kind == "tone_sets" else request.app.state.config.tone_sets,
            sources=items if kind == "sources" else request.app.state.config.sources,
            alert_targets=items
            if kind == "alert_targets"
            else request.app.state.config.alert_targets,
            discovery=request.app.state.config.discovery,
        )
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    return await save_config(request, config)


def base_path(request: Request) -> str:
    path = request.headers.get("x-ingress-path", "") if request.state.auth == "ingress" else ""
    return "/" + path.strip("/") if path.strip("/") else ""
