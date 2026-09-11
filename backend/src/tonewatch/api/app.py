"""FastAPI application factory, middleware, exception handlers, and lifespan."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from tonewatch.api.auth import AuthState
from tonewatch.api.routes.analyze import router as analyze_router
from tonewatch.api.routes.auth import router as auth_router
from tonewatch.api.routes.calls import router as calls_router
from tonewatch.api.routes.config import router as config_router
from tonewatch.api.routes.recordings import router as recordings_router
from tonewatch.api.routes.system import router as system_router
from tonewatch.api.routes.ws import router as ws_router
from tonewatch.config.models import AppConfig
from tonewatch.config.store import ConfigStore
from tonewatch.events import EventBus
from tonewatch.integrations.supervisor import register_supervisor_discovery
from tonewatch.integrations.zeroconf import ZeroconfAdvertiser
from tonewatch.logging import clear_request_id, configure_logging, set_request_id
from tonewatch.pipeline.supervisor import Supervisor
from tonewatch.sources.soundcard import input_devices as _input_devices
from tonewatch.storage.db import create_database, upgrade_database

MAX_ANALYZE_BYTES = 20 * 1024 * 1024 + 64 * 1024


def input_devices() -> list[dict[str, object]]:
    """Compatibility export for the device CLI/API boundary."""
    return _input_devices()


def create_app(
    settings: Any,
    *,
    supervisor: Any = None,
    session_factory: Any = None,
    store: ConfigStore | None = None,
    clock: Any = None,
) -> FastAPI:
    """Create an isolated API application with injectable runtime dependencies."""
    auth = AuthState(settings, clock or __import__("time").time)
    configure_logging(settings.log_level, json=True, api_token=auth.token)
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
        calls_router,
        recordings_router,
        analyze_router,
        system_router,
        ws_router,
    ):
        app.include_router(router)
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
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'self'"
        structlog.get_logger("tonewatch.api").info(
            "request", method=request.method, path=request.url.path, status=response.status_code
        )
        clear_request_id(context_tokens)
        return response

    @app.exception_handler(Exception)
    async def safe_error(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> Any:
        try:
            if app.state.engine is not None:
                await upgrade_database(app.state.engine)
            app.state.config = config_store.load()
            if app.state.supervisor is None:
                app.state.supervisor = Supervisor(app.state.config, bus, sessions)
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
