"""Safe, atomic YAML configuration persistence."""

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from tonewatch.config.models import AppConfig


class ConfigError(ValueError):
    """Raised when the YAML configuration cannot be read or validated."""


class ConfigStore:
    """Load and atomically save the application YAML configuration."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "config.yaml"

    def load(self) -> AppConfig:
        """Load config, creating a default file on first run."""
        if not self.path.exists():
            config = AppConfig()
            self.save(config)
            return config
        try:
            with self.path.open(encoding="utf-8") as handle:
                raw: Any = yaml.safe_load(handle)
            return AppConfig.model_validate(raw or {})
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {self.path}: {exc}") from exc
        except ValidationError as exc:
            raise ConfigError(f"invalid configuration in {self.path}: {exc}") from exc

    def save(self, config: AppConfig) -> None:
        """Write config, retaining a backup and replacing atomically."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False)
        if self.path.exists():
            backup = self.path.with_suffix(".yaml.bak")
            backup.write_bytes(self.path.read_bytes())
        fd, temporary = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=self.data_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            with suppress(OSError):
                Path(temporary).unlink(missing_ok=True)
            raise ConfigError(f"could not atomically save {self.path}: {exc}") from exc
