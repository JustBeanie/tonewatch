"""Runtime settings and Home Assistant add-on bootstrap."""

import json
import os
from pathlib import Path
from typing import Any, cast

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from tonewatch.recording.retention import RetentionPolicy


class Settings(BaseSettings):
    """Application settings, overridable with TONEWATCH_ environment variables."""

    model_config = SettingsConfigDict(env_prefix="TONEWATCH_", extra="ignore")

    data_dir: Path = Path("data")
    log_level: str = "INFO"
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
    ui_password: str | None = None
    recordings_root: Path | None = None
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)

    @classmethod
    def load(cls, *, options_path: Path = Path("/data/options.json")) -> "Settings":
        """Load environment settings and optional Supervisor add-on options."""
        values: dict[str, object] = {}
        addon = bool(os.getenv("SUPERVISOR_TOKEN"))
        if addon and options_path.is_file():
            with options_path.open(encoding="utf-8") as handle:
                options = json.load(handle)
            if isinstance(options, dict):
                supported = {"data_dir", "log_level", "bind_host", "bind_port"}
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

    @property
    def recording_path(self) -> Path:
        """Return the configured recording directory."""
        if self.addon_mode and self.recordings_root is None:
            return Path("/media/tonewatch")
        return (self.recordings_root or self.data_dir / "recordings").resolve()
