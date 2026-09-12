"""Integration coverage for backend hosted SPA behavior."""

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urljoin

import httpx
import pytest

from tonewatch.api.app import create_app
from tonewatch.settings import Settings


class NoopSupervisor:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


def make_app(root: Path, web_root: Path, *, addon_mode: bool = False) -> Any:
    return create_app(
        Settings(
            data_dir=root,
            web_root=web_root,
            addon_mode=addon_mode,
            zeroconf_enabled=False,
        ),
        supervisor=NoopSupervisor(),
        session_factory=lambda: None,
    )


def write_dist(root: Path) -> None:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<!doctype html><html><head><base href="/"></head>'
        '<body><div id="root"></div><script type="module" src="./assets/app.js"></script>'
        "</body></html>",
        encoding="utf-8",
    )
    (root / "assets" / "app.js").write_text("console.log('ok');", encoding="utf-8")


@pytest.mark.asyncio
async def test_spa_served_with_history_fallback() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        write_dist(dist)
        app = make_app(root / "data", dist)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/tonesets/new", headers={"Accept": "text/html"})
        assert response.status_code == 200
        assert 'id="root"' in response.text
        assert response.headers["cache-control"] == "no-cache"


@pytest.mark.asyncio
async def test_spa_does_not_shadow_api_routes_or_401s() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        write_dist(dist)
        app = make_app(root / "data", dist)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            unknown = await client.get("/api/x", headers={"Accept": "text/html"})
            protected = await client.get("/api/tonesets")
        assert unknown.status_code == 404 and unknown.headers["content-type"].startswith(
            "application/json"
        )
        assert protected.status_code == 401 and protected.headers["content-type"].startswith(
            "application/json"
        )
        assert "root" not in unknown.text and "root" not in protected.text


@pytest.mark.asyncio
async def test_spa_html_csp_allows_self_only() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        write_dist(dist)
        app = make_app(root / "data", dist)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            html = await client.get("/")
            api = await client.get("/api/x")
        csp = html.headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp and "style-src 'self'" in csp
        assert "connect-src 'self';" in csp
        assert "ws:" not in csp and "wss:" not in csp
        assert "'unsafe-inline'" not in csp and "https://" not in csp
        assert (
            api.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'self'"
        )


@pytest.mark.asyncio
async def test_static_assets_have_immutable_cache_headers() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        write_dist(dist)
        app = make_app(root / "data", dist)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            asset = await client.get("/assets/app.js")
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "console.log" in asset.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/assets/../../api_token", "/assets/%2e%2e/%2e%2e/api_token"])
async def test_spa_path_traversal_refused(path: str) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        write_dist(dist)
        (dist.parent / "api_token").write_text("secret", encoding="utf-8")
        app = make_app(root / "data", dist)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(path)
        assert response.status_code in {400, 404}
        assert "secret" not in response.text


@pytest.mark.asyncio
async def test_spa_deep_link_assets_resolve() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        write_dist(dist)
        app = make_app(root / "data", dist)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            document = await client.get("/tonesets/new", headers={"Accept": "text/html"})
            base_href = re.search(r'<base href="([^"]+)">', document.text)
            asset_src = re.search(r'<script type="module" src="([^"]+)"></script>', document.text)
            assert base_href is not None
            assert asset_src is not None
            document_base = urljoin(str(document.url), base_href.group(1))
            asset_url = urljoin(document_base, asset_src.group(1))
            asset = await client.get(asset_url)
        assert document.status_code == 200
        assert asset.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("peer", "expected"), [("172.30.32.2", "/api/hassio_ingress/token/"), ("10.0.0.1", "/")]
)
async def test_spa_ingress_prefix_base(peer: str, expected: str) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        write_dist(dist)
        app = make_app(root / "data", dist, addon_mode=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(peer, 1)), base_url="http://test"
        ) as client:
            response = await client.get(
                "/tonesets/new",
                headers={"Accept": "text/html", "X-Ingress-Path": "/api/hassio_ingress/token"},
            )
        assert f'<base href="{expected}">' in response.text


@pytest.mark.asyncio
async def test_spa_ingress_prefix_rejects_malformed_path() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        write_dist(dist)
        app = make_app(root / "data", dist, addon_mode=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("172.30.32.2", 1)),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/tonesets/new",
                headers={
                    "Accept": "text/html",
                    "X-Ingress-Path": '/api/hassio_ingress/tok"><script>alert(1)</script>',
                },
            )
        assert '<base href="/">' in response.text
        assert "<script>alert(1)</script>" not in response.text
