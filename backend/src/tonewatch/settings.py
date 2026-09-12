"""Runtime settings and Home Assistant add-on bootstrap."""

import json
import os
import sys
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import structlog
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tonewatch.recording.retention import RetentionPolicy


def _default_data_dir() -> Path:
    """Return the development or frozen Windows data directory."""
    if getattr(sys, "frozen", False) and not os.getenv("TONEWATCH_DATA_DIR"):
        return Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "tonewatch"
    return Path("data")


class SettingsValueError(ValueError):
    """A settings value failed its add-on contract."""

    def __init__(self) -> None:
        """Build the stable validation message used by Pydantic."""
        super().__init__("invalid add-on option")


def _default_web_root() -> Path | None:
    package_root = Path(__file__).resolve().parent / "web_dist"
    if package_root.is_dir():
        return package_root
    source_root = Path(__file__).resolve().parents[3] / "web" / "dist"
    if source_root.is_dir():
        return source_root
    return None


class Settings(BaseSettings):
    """Application settings, overridable with TONEWATCH_ environment variables."""

    model_config = SettingsConfigDict(env_prefix="TONEWATCH_", extra="ignore")

    data_dir: Path = Field(default_factory=_default_data_dir)
    log_level: str = "INFO"
    mqtt_mode: str = "supervisor"
    public_base_url: str | None = None
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8099, ge=1, le=65535)
    addon_mode: bool = False
    zeroconf_enabled: bool = True
    allow_script_targets: bool = False
    script_allowlist_dirs: list[Path] = Field(default_factory=list)
    webhook_block_private: bool = False
    webhook_allow_redirects: bool = False
    webhook_attachment_max_bytes: int = Field(default=10 * 1024 * 1024, ge=0)
    stream_block_private: bool = False
    analyze_decode_timeout_s: float = Field(default=10, gt=0, le=60)
    ha_integration_enabled: bool = False
    instance_id: str | None = None
    ui_password: str | None = Field(default=None, repr=False)
    web_root: Path | None = Field(default_factory=_default_web_root)
    recordings_root: Path | None = None
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Accept the manifest's lower-case values and legacy upper-case values."""
        if value.casefold() not in {"debug", "info", "warning", "error"}:
            raise SettingsValueError
        return value

    @field_validator("mqtt_mode")
    @classmethod
    def validate_mqtt_mode(cls, value: str) -> str:
        """Restrict add-on MQTT behavior to the documented modes."""
        if value not in {"supervisor", "manual", "off"}:
            raise SettingsValueError
        return value

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, value: str | None) -> str | None:
        """Accept only origin/path URLs that do not carry credentials or fragments."""
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SettingsValueError
        if parsed.username is not None or parsed.password is not None:
            raise SettingsValueError
        if parsed.query or parsed.fragment:
            raise SettingsValueError
        try:
            _ = parsed.port
        except ValueError as exc:
            raise SettingsValueError from exc
        return value.rstrip("/")

    @classmethod
    def load(cls, *, options_path: Path = Path("/data/options.json")) -> "Settings":
        """Load environment settings and optional Supervisor add-on options."""
        values: dict[str, object] = {}
        addon = bool(os.getenv("SUPERVISOR_TOKEN"))
        if addon and options_path.is_file():
            with options_path.open(encoding="utf-8") as handle:
                options = json.load(handle)
            if isinstance(options, dict):
                supported = {
                    "data_dir",
                    "log_level",
                    "bind_host",
                    "bind_port",
                    "mqtt_mode",
                    "public_base_url",
                    "ui_password",
                }
                unknown = sorted(set(options) - supported)
                if unknown:
                    structlog.get_logger("tonewatch.settings").warning(
                        "unknown add-on options ignored", keys=unknown
                    )
                values.update(
                    {
                        key: value
                        for key, value in options.items()
                        if key in supported and f"TONEWATCH_{key.upper()}" not in os.environ
                    }
                )
        values["addon_mode"] = addon
        if addon:
            values["zeroconf_enabled"] = False
        return cls(**cast("dict[str, Any]", values))

    def __repr__(self) -> str:
        """Avoid exposing the optional UI password through diagnostics."""
        fields = self.model_dump(exclude={"ui_password"})
        return f"Settings({fields!r})"

    @property
    def recording_path(self) -> Path:
        """Return the configured recording directory."""
        if self.addon_mode and self.recordings_root is None:
            return Path("/media/tonewatch")
        return (self.recordings_root or self.data_dir / "recordings").resolve()
