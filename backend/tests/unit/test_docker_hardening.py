"""Regression checks for the documented Docker deployment contract."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]
COMPOSE_FILES = (
    ROOT / "docker/compose.soundcard.yml",
    ROOT / "docker/compose.stream.yml",
    ROOT / "docker/compose.rtlsdr.yml",
)


def test_compose_files_are_hardened() -> None:
    """Every example keeps the M8 least-privilege runtime contract."""
    for path in COMPOSE_FILES:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        services = document["services"]
        assert services
        for service in services.values():
            assert service["read_only"] is True, path
            assert service["cap_drop"] == ["ALL"], path
            assert "no-new-privileges:true" in service["security_opt"], path
            assert "/tmp" in service["tmpfs"], path  # noqa: S108 -- compose tmpfs mount, not a temp file.
            assert service["healthcheck"], path
            ports = service["ports"]
            assert any(
                str(port.get("target", "")) == "8099" and str(port.get("published", "")) == "8099"
                for port in ports
                if isinstance(port, dict)
            ) or any(str(port).split(":")[-1].split("/")[0] == "8099" for port in ports), path
