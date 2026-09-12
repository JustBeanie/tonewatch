"""Static SPA serving and history fallback for the HTTP application."""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import unquote

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

SPA_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    # CSP3 'self' already matches same-origin ws:/wss:; bare ws:/wss: would allow any host.
    "connect-src 'self'; img-src 'self'; media-src 'self'; "
    "font-src 'self'; frame-ancestors 'self'"
)


def _not_found() -> JSONResponse:
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def _request_path_is_unsafe(request: Request, path: str) -> bool:
    raw_path = request.scope.get("raw_path", b"")
    raw = raw_path.decode("latin-1") if isinstance(raw_path, bytes) else str(raw_path)
    for value in (path, raw, unquote(raw), unquote(unquote(raw))):
        normalized = value.replace("\\", "/")
        if any(part == ".." for part in normalized.split("/")):
            return True
    return "\x00" in path


def _safe_file(root: Path, path: str) -> Path | None:
    try:
        candidate = (root / Path(path)).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def _ingress_prefix(request: Request) -> str:
    auth = getattr(request.app.state, "auth", None)
    if auth is None or not auth.ingress_valid(request):
        return ""
    return "/" + request.headers["x-ingress-path"].strip("/")


def _html_response(root: Path, request: Request) -> Response:
    index = root / "index.html"
    if not index.is_file():
        return _not_found()
    document = index.read_text(encoding="utf-8")
    base = f"{_ingress_prefix(request)}/"
    base_tag = f'<base href="{html.escape(base, quote=True)}">'
    lower = document.lower()
    start = lower.find("<base ")
    if start >= 0:
        end = lower.find(">", start)
        if end >= 0:
            document = document[:start] + base_tag + document[end + 1 :]
    elif "<head" in lower:
        head_end = document.find(">", lower.find("<head"))
        document = document[: head_end + 1] + base_tag + document[head_end + 1 :]
    else:
        document = base_tag + document
    return Response(
        document,
        media_type="text/html",
        headers={"Cache-Control": "no-cache", "Content-Security-Policy": SPA_CSP},
    )


async def serve_spa(request: Request, root: Path | None) -> Response:
    """Serve a static file or the SPA document after application routes decline."""
    path = request.url.path.lstrip("/")
    if root is None or not root.is_dir() or _request_path_is_unsafe(request, path):
        return _not_found()
    if path == "" or path == "index.html":
        return _html_response(root, request)
    if path == "api" or path.startswith("api/"):
        return _not_found()
    asset = _safe_file(root, path)
    if asset is not None:
        headers = (
            {"Cache-Control": "public, max-age=31536000, immutable"}
            if path.startswith("assets/")
            else {}
        )
        return FileResponse(asset, headers=headers)
    if path.startswith("assets/") or "text/html" not in request.headers.get("accept", "").lower():
        return _not_found()
    return _html_response(root, request)


def register_spa(app: FastAPI, web_root: Path | None) -> None:
    """Store the SPA root and report clearly when its build is unavailable."""
    logger = structlog.get_logger("tonewatch.api.spa")
    root = web_root.resolve() if web_root is not None else None
    if root is None or not root.is_dir():
        logger.warning("spa disabled: web root does not exist", web_root=str(web_root))
    app.state.spa_root = root
