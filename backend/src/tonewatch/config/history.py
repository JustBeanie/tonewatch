"""File-backed configuration history with secret-safe read operations."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import ValidationError

from tonewatch.api.audit import is_secret_key, mask_secrets
from tonewatch.config.models import AppConfig

MAX_VERSIONS = 100


class HistoryError(ValueError):
    """A stored history version is missing or invalid."""


def canonical_content(config: AppConfig | dict[str, Any]) -> bytes:
    """Return deterministic JSON bytes used for version hashes."""
    raw = config.model_dump(mode="json") if hasattr(config, "model_dump") else config
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        rows: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}" if path else str(key)
            rows.extend(_diff(before.get(key), after.get(key), child))
        return rows
    if isinstance(before, list) and isinstance(after, list):
        rows = []
        for index in range(max(len(before), len(after))):
            rows.extend(
                _diff(
                    before[index] if index < len(before) else None,
                    after[index] if index < len(after) else None,
                    f"{path}[{index}]",
                )
            )
        return rows
    if before == after:
        return []
    key = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if is_secret_key(key) and (before not in (None, "") or after not in (None, "")):
        return [{"path": path, "before": "changed", "after": "changed"}]
    return [{"path": path, "before": mask_secrets(before), "after": mask_secrets(after)}]


def structured_diff(before: Any, after: Any) -> list[dict[str, Any]]:
    """Build a secret-safe path diff between two JSON-like documents."""
    return _diff(before, after)


class ConfigHistory:
    """Persist immutable config snapshots beneath the configured data directory."""

    def __init__(self, data_dir: Path) -> None:
        """Create a history view rooted below ``data_dir``."""
        self.root = data_dir / "config-history"

    def _path(self, version_id: str) -> Path:
        if (
            not version_id
            or Path(version_id).name != version_id
            or "/" in version_id
            or "\\" in version_id
        ):
            raise HistoryError("invalid configuration version id")  # noqa: TRY003 -- stable API error
        return self.root / f"{version_id}.yaml"

    def record(self, config: AppConfig, *, actor: str, route: str) -> dict[str, Any]:
        """Write one secret-bearing snapshot atomically and prune old snapshots."""
        raw = config.model_dump(mode="json")
        version: dict[str, Any] = {
            "id": uuid4().hex,
            "time": datetime.now(UTC).isoformat(),
            "actor": actor,
            "route": route,
            "sha256": hashlib.sha256(canonical_content(raw)).hexdigest(),
            "config": raw,
        }
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".version.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                yaml.safe_dump(version, handle, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                Path(temporary).chmod(0o600)
            Path(temporary).replace(self._path(version["id"]))
        except OSError as exc:
            Path(temporary).unlink(missing_ok=True)
            raise HistoryError(f"could not save configuration history: {exc}") from exc  # noqa: TRY003 -- actionable storage error
        self._prune()
        return {key: version[key] for key in ("id", "time", "actor", "route", "sha256")}

    def _read(self, version_id: str) -> dict[str, Any]:
        path = self._path(version_id)
        try:
            with path.open(encoding="utf-8") as handle:
                value = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            raise HistoryError("configuration version is unavailable") from exc  # noqa: TRY003 -- stable API error
        if not isinstance(value, dict) or not isinstance(value.get("config"), dict):
            raise HistoryError("configuration version is invalid")  # noqa: TRY003 -- stable API error
        return value

    def _prune(self) -> None:
        paths = sorted(
            self.root.glob("*.yaml"), key=lambda path: path.stat().st_mtime, reverse=True
        )
        for path in paths[MAX_VERSIONS:]:
            path.unlink(missing_ok=True)

    def list_versions(self) -> list[dict[str, Any]]:
        """Return newest-first metadata without snapshot content."""
        if not self.root.exists():
            return []
        values = []
        for path in self.root.glob("*.yaml"):
            try:
                value = self._read(path.stem)
                values.append(
                    {key: value.get(key) for key in ("id", "time", "actor", "route", "sha256")}
                )
            except HistoryError:
                continue
        return sorted(values, key=lambda value: str(value.get("time", "")), reverse=True)

    def config(self, version_id: str) -> AppConfig:
        """Load and validate one stored configuration snapshot."""
        value = self._read(version_id)
        try:
            return AppConfig.model_validate(value["config"])
        except ValidationError as exc:
            raise HistoryError(f"stored configuration no longer validates: {exc}") from exc  # noqa: TRY003 -- readable validation reason

    def masked_content(self, version_id: str) -> dict[str, Any]:
        """Return one snapshot with credentials recursively masked."""
        return mask_secrets(self._read(version_id)["config"])

    def raw_config(self, version_id: str) -> dict[str, Any]:
        """Return one stored configuration snapshot for internal diff/validation use."""
        return self._read(version_id)["config"]

    def diff(self, before_id: str, after_id: str) -> list[dict[str, Any]]:
        """Return a structured, secret-safe diff between two snapshots."""
        return _diff(self._read(before_id)["config"], self._read(after_id)["config"])
