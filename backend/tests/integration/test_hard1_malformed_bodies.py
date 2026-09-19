"""HARD1 regression matrix for malformed bodies on mutating API routes."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from tonewatch.api.app import create_app
from tonewatch.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


_ZAP_QUERY = "?-d+allow_url_include%3d1+-d+auto_prepend_file%3dphp://input"
_CASES: tuple[tuple[str, bytes, str], ...] = (
    ("empty", b"", ""),
    ("not-json", b"not json", "application/json"),
    ("array", b"[]", "application/json"),
    ("string", b'"string"', "application/json"),
    ("number", b"123", "application/json"),
    ("unexpected-object", b'{"unexpected":true}', "application/json"),
    ("one-megabyte", b"x" * (1024 * 1024), "application/octet-stream"),
    ("zap-query", b"", ""),
)
_SENSITIVE_RESPONSE_MARKERS = ("traceback", "exception")
_FILE_PATH = re.compile(r"(?:[a-z]:\\|/(?:home|usr|app|workspace)/)[^\s\"']+")


def _route_path(route: Any) -> str:
    """Make a deterministic request path for every registered route."""
    path = route.path
    replacements = {
        "version_id": "missing-version",
        "attempt_id": "0",
        "item_id": "missing-item",
        "source_id": "missing-source",
        "toneset_id": "missing-toneset",
        "key": "missing-key",
        "recording_id": "0",
        "call_id": "0",
        "target_id": "missing-target",
        "discovered_id": "missing-discovered",
        "upload_id": "missing-upload",
    }
    for name, value in replacements.items():
        path = path.replace("{" + name + "}", value)
    return path


def _mutating_routes(app: Any) -> list[tuple[str, str]]:
    registered_routes = [
        child
        for route in app.routes
        for child in getattr(getattr(route, "original_router", None), "routes", (route,))
    ]
    return sorted(
        {
            (method, _route_path(route))
            for route in registered_routes
            if hasattr(route, "methods") and hasattr(route, "path")
            for method in route.methods or ()
            if method in {"POST", "PUT", "PATCH", "DELETE"}
        }
    )


@asynccontextmanager
async def _client(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    app = create_app(Settings(data_dir=tmp_path, zeroconf_enabled=False))
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    try:
        yield client, app
    finally:
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_mutating_routes_reject_malformed_bodies_without_server_errors(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as (client, app):
        routes = _mutating_routes(app)
        assert routes
        failures: list[str] = []
        for method, route in routes:
            for name, body, content_type in _CASES:
                query = _ZAP_QUERY if name == "zap-query" else ""
                request_headers = {"Authorization": f"Bearer {app.state.auth.token}"}
                if content_type:
                    request_headers["Content-Type"] = content_type
                response = await client.request(
                    method,
                    route + query,
                    content=body,
                    headers=request_headers,
                )
                text = response.text.casefold()
                if (
                    response.status_code >= 500
                    or any(marker in text for marker in _SENSITIVE_RESPONSE_MARKERS)
                    or _FILE_PATH.search(text)
                ):
                    failures.append(
                        f"{method} {route} [{name}] -> {response.status_code}: {response.text}"
                    )
        assert not failures, "\n".join(failures)
