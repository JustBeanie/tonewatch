"""Async mDNS advertisement for ToneWatch."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from tonewatch import __version__

if TYPE_CHECKING:
    from pathlib import Path


def instance_id(data_dir: Path) -> UUID:
    """Read or create the stable instance identifier."""
    path = data_dir / "instance_id"
    if path.is_file():
        return UUID(path.read_text(encoding="ascii").strip())
    value = uuid4()
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value) + "\n", encoding="ascii")
    return value


class ZeroconfAdvertiser:
    """Register and unregister the local mDNS service."""

    def __init__(self, data_dir: Path, port: int, *, enabled: bool = True) -> None:
        """Create an advertiser for the configured data directory and port."""
        self.data_dir, self.port, self.enabled = data_dir, port, enabled
        self._zeroconf: AsyncZeroconf | None = None
        self._info: ServiceInfo | None = None

    async def start(self) -> None:
        """Register the service when discovery is enabled."""
        if not self.enabled:
            return
        iid = instance_id(self.data_dir)
        self._zeroconf = AsyncZeroconf()
        self._info = ServiceInfo(
            "_tonewatch._tcp.local.",
            f"ToneWatch-{iid}._tonewatch._tcp.local.",
            addresses=[b"\x7f\x00\x00\x01"],
            port=self.port,
            properties={"version": __version__, "api": "/api", "instance_id": str(iid)},
        )
        await self._zeroconf.async_register_service(self._info)

    async def stop(self) -> None:
        """Unregister and close the async zeroconf client."""
        if self._zeroconf is not None and self._info is not None:
            await self._zeroconf.async_unregister_service(self._info)
            await self._zeroconf.async_close()
        self._zeroconf = None
        self._info = None
