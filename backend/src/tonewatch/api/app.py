"""FastAPI application factory, middleware, exception handlers, and lifespan."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect

from tonewatch.api.auth import AuthState
from tonewatch.api.routes.analyze import router as analyze_router
from tonewatch.api.routes.audit import router as audit_router
from tonewatch.api.routes.auth import router as auth_router
from tonewatch.api.routes.calls import router as calls_router
from tonewatch.api.routes.config import router as config_router
from tonewatch.api.routes.discovered_tones import router as discovered_tones_router
from tonewatch.api.routes.import_tones_cfg import router as import_tones_cfg_router
from tonewatch.api.routes.recordings import router as recordings_router
from tonewatch.api.routes.system import router as system_router
from tonewatch.api.routes.ws import router as ws_router
from tonewatch.api.spa import SPA_CSP, register_spa, serve_spa
from tonewatch.config.models import AppConfig
from tonewatch.config.store import ConfigStore
from tonewatch.events import EventBus
from tonewatch.integrations.supervisor import (
    ensure_addon_mqtt_target,
    register_supervisor_discovery,
)
from tonewatch.integrations.zeroconf import ZeroconfAdvertiser, instance_id
from tonewatch.logging import clear_request_id, configure_logging, set_request_id
from tonewatch.pipeline.supervisor import Supervisor
from tonewatch.recording.retention import RetentionService
from tonewatch.sources.soundcard import input_devices as _input_devices
from tonewatch.storage.db import create_database, upgrade_database

MAX_ANALYZE_BYTES = 20 * 1024 * 1024 + 64 * 1024
MAX_TONES_CFG_IMPORT_BYTES = 256 * 1024


def _parse_content_length(value: str | None) -> int | None:
    """Parse an optional Content-Length, rejecting malformed and negative values."""
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Content-Length") from exc
    if length < 0:
        raise ValueError("invalid Content-Length")
    return length


async def _send_json(
    send: Callable[[dict[str, Any]], Awaitable[None]], status: int, detail: str
) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _TonesCfgBodyLimitMiddleware:
    """Bound tones.cfg request bytes without depending on Starlette private attributes."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        path = str(scope.get("path", ""))
        root_path = str(scope.get("root_path", ""))
        if (
            root_path
            and root_path != "/"
            and (path == root_path or path.startswith(root_path + "/"))
        ):
            path = path[len(root_path) :] or "/"
        if scope.get("type") != "http" or path.rstrip("/") != "/api/import/tones-cfg":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        content_type = headers.get("content-type", "").casefold()
        request_limit = (
            self.max_bytes + 64 * 1024
            if content_type.startswith("multipart/form-data")
            else self.max_bytes
        )
        try:
            content_length = _parse_content_length(headers.get("content-length"))
        except ValueError:
            await _send_json(send, 400, "invalid Content-Length")
            return
        if content_length is not None and content_length > request_limit:
            await _send_json(send, 413, "upload too large")
            return

        received = 0
        rejected = False

        async def limited_receive() -> dict[str, Any]:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > request_limit:
                    rejected = True
                    await _send_json(send, 413, "upload too large")
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: dict[str, Any]) -> None:
            if not rejected:
                await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except ClientDisconnect:
            if not rejected:
                raise


def input_devices() -> list[dict[str, object]]:
    """Compatibility export for the device CLI/API boundary."""
    return _input_devices()


def _set_api_csp(response: Any) -> None:
    """Deny all content for non-HTML API responses while forbidding foreign framing."""
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"
    )


def create_app(
    settings: Any,
    *,
    supervisor: Any = None,
    session_factory: Any = None,
    store: ConfigStore | None = None,
    clock: Any = None,
    sleep: Any = None,
    source_factory: Any = None,
    watchdog_no_data_s: float = 10,
    shutdown_timeout_s: float = 5,
    shutdown_finalize_timeout_s: float | None = None,
    shutdown_drain_timeout_s: float | None = None,
    encoder_factory: Any = None,
) -> FastAPI:
    """Create an isolated API application with injectable runtime dependencies."""
    auth = AuthState(settings, clock or __import__("time").time)
    configure_logging(
        settings.log_level,
        json=True,
        api_token=auth.token,
        data_dir=settings.data_dir,
    )
    config_store = store or ConfigStore(settings.data_dir)
    engine = None
    sessions = session_factory
    if sessions is None:
        engine, sessions = create_database(
            f"sqlite+aiosqlite:///{settings.data_dir / 'tonewatch.db'}"
        )
    bus = EventBus()
    app = FastAPI(title="ToneWatch API", docs_url=None, redoc_url=None)
    for router in (
        auth_router,
        config_router,
        discovered_tones_router,
        import_tones_cfg_router,
        calls_router,
        recordings_router,
        analyze_router,
        audit_router,
        system_router,
        ws_router,
    ):
        app.include_router(router)
    register_spa(app, settings.web_root)
    app.state.settings = settings
    app.state.ready = False
    app.state.config = AppConfig()
    app.state.auth = auth
    app.state.bus = bus
    app.state.session_factory = sessions
    app.state.supervisor = supervisor
    app.state.store = config_store
    app.state.engine = engine
    app.state.ws_hub = None
    app.state.ws_pump = None
    advertiser = ZeroconfAdvertiser(
        settings.data_dir,
        settings.bind_port,
        enabled=settings.zeroconf_enabled and not settings.addon_mode,
    )
    app.add_middleware(_TonesCfgBodyLimitMiddleware, max_bytes=MAX_TONES_CFG_IMPORT_BYTES)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        context_tokens = set_request_id(request_id)
        try:
            response: Response | None = None
            if request.method == "POST" and request.url.path == "/api/analyze":
                content_length = request.headers.get("content-length")
                if content_length and int(content_length) > MAX_ANALYZE_BYTES:
                    response = JSONResponse({"detail": "upload too large"}, status_code=413)
                if response is None and not content_length:
                    original_receive = request._receive
                    buffered: list[Any] = []
                    received = 0
                    while True:
                        message = await original_receive()
                        buffered.append(message)
                        received += len(message.get("body", b""))
                        if received > MAX_ANALYZE_BYTES:
                            response = JSONResponse({"detail": "upload too large"}, status_code=413)
                            break
                        if not message.get("more_body", False):
                            break
                    if response is None:
                        replay = iter(buffered)

                        async def replay_receive() -> Any:
                            return next(replay, {"type": "http.disconnect"})

                        request._receive = replay_receive
            if response is None:
                response = await call_next(request)
            if response.status_code == 404 and request.method == "GET":
                response = await serve_spa(request, app.state.spa_root)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        except Exception:
            structlog.get_logger("tonewatch.api").exception(
                "request failed", method=request.method, path=request.url.path
            )
            response = JSONResponse({"detail": "internal server error"}, status_code=500)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        # The UI never uses browser device APIs: audio capture happens server-side.
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), usb=(), payment=()"
        )
        # Every UI subresource is same-origin, and recordings need same-site cookies or a bearer
        # token, so cross-origin embedding is never a supported use.
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = SPA_CSP
        else:
            _set_api_csp(response)
        structlog.get_logger("tonewatch.api").info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            security_redaction="[REDACTED]",
            authorization="[REDACTED]" if request.headers.get("authorization") else None,
            cookie="[REDACTED]" if request.headers.get("cookie") else None,
        )
        clear_request_id(context_tokens)
        return response

    @app.exception_handler(Exception)
    async def safe_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> Any:
        try:
            runtime_clock = clock or time.time
            if app.state.engine is not None:
                await upgrade_database(app.state.engine)
            app.state.config = config_store.load()
            app.state.config = ensure_addon_mqtt_target(app.state.config, settings, config_store)
            if app.state.supervisor is None:
                app.state.supervisor = Supervisor(
                    app.state.config,
                    bus,
                    sessions,
                    clock=runtime_clock,
                    sleep=sleep or asyncio.sleep,
                    retention_service=RetentionService(
                        settings.recording_path,
                        settings.retention,
                        clock=runtime_clock,
                    ),
                    source_factory=source_factory,
                    watchdog_no_data_s=watchdog_no_data_s,
                    shutdown_timeout_s=shutdown_timeout_s,
                    shutdown_finalize_timeout_s=shutdown_finalize_timeout_s,
                    shutdown_drain_timeout_s=shutdown_drain_timeout_s,
                    encoder_factory=encoder_factory,
                    settings=settings,
                    instance_id=str(settings.instance_id or instance_id(settings.data_dir)),
                )
            await app.state.supervisor.start()
            await advertiser.start()
            await register_supervisor_discovery(
                settings.bind_port,
                addon_mode=settings.addon_mode,
            )
            app.state.ready = True
            yield
        finally:
            await advertiser.stop()
            if app.state.ws_pump is not None:
                app.state.ws_pump.cancel()
                await asyncio.gather(app.state.ws_pump, return_exceptions=True)
            if app.state.supervisor is not None:
                await app.state.supervisor.stop()
            if app.state.engine is not None:
                await app.state.engine.dispose()

    app.router.lifespan_context = lifespan
    return app
