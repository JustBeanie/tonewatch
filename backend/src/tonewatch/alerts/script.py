"""安全 shell-free script alert target."""

from __future__ import annotations

import asyncio
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tonewatch.config.models import ScriptTarget


@dataclass(frozen=True)
class ScriptResult:
    """Outcome and bounded process output."""

    ok: bool
    status_code: int | None = None
    error: str | None = None


def resolve_executable(target: ScriptTarget, allowlist_dirs: list[Path]) -> Path:
    """Resolve an executable and prove it remains inside an allowed directory."""
    candidate = Path(target.executable)
    if not candidate.is_absolute() or not allowlist_dirs:
        raise ValueError("script executable is not allowlisted")
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file() or not any(
            resolved.is_relative_to(directory.resolve()) for directory in allowlist_dirs
        ):
            raise ValueError("script executable is not allowlisted")
        if os.name == "posix" and stat.S_IWOTH & resolved.stat().st_mode:
            raise ValueError("script executable is world-writable")
    except (FileNotFoundError, OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "script executable is not allowlisted":
            raise
        raise ValueError("script executable is not allowlisted") from exc
    return resolved


def argv_for(target: ScriptTarget, values: dict[str, str]) -> list[str]:
    """Expand templates as strings; no shell or secondary argument parsing occurs."""
    return [template.format_map(values) for template in target.args]


async def run_script(
    target: ScriptTarget,
    payload: dict[str, Any],
    *,
    allow_script_targets: bool,
    allowlist_dirs: list[Path],
) -> ScriptResult:
    """Run one configured script with only safe, explicit process inputs."""
    if not allow_script_targets or not target.enabled:
        return ScriptResult(False, error="script target disabled")
    try:
        executable = resolve_executable(target, allowlist_dirs)
        values = {
            "call_id": str(payload.get("call_id", "")),
            "toneset": str(payload.get("toneset", "")),
            "recording_path": str(payload.get("recording_path", "")),
            "source_id": str(payload.get("source_id", "")),
            "phase": str(payload.get("phase", "")),
        }
        argv = argv_for(target, values)
    except ValueError as exc:
        return ScriptResult(False, error=str(exc)[:500])
    env = {"PATH": "/usr/bin:/bin"}
    for key, value in values.items():
        env[f"TONEWATCH_{key.upper()}"] = value
    with tempfile.TemporaryDirectory(prefix="tonewatch-script-") as cwd:
        try:
            process = await asyncio.create_subprocess_exec(
                str(executable),
                *argv,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), target.timeout_s)
            except TimeoutError:
                process.kill()
                stdout, stderr = await process.communicate()
                output = (stdout + stderr).decode(errors="replace")[:4096]
                return ScriptResult(False, error=f"script timeout: {output}")
        except (OSError, subprocess.SubprocessError) as exc:
            return ScriptResult(False, error=str(exc)[:500])
    output = (stdout + stderr).decode(errors="replace")[:4096]
    if process.returncode == 0:
        return ScriptResult(True, status_code=0, error=output or None)
    return ScriptResult(False, status_code=process.returncode, error=output or "script failed")
