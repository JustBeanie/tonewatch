"""Shared WAV analysis used by the CLI and HTTP API."""

import asyncio
from pathlib import Path
from typing import Any

import yaml

from tonewatch.__main__ import _json_output, _read_wav
from tonewatch.config.models import AppConfig
from tonewatch.dsp.engine import DetectionEngine


def analyze_wav(path: Path, config: AppConfig) -> dict[str, Any]:
    samples, _ = _read_wav(path)
    return _json_output(DetectionEngine(config.tone_sets).feed(samples), False)


async def analyze_wav_with_timeout(
    path: Path, config: AppConfig, *, timeout_s: float = 10
) -> dict[str, Any]:
    """Decode an uploaded file off-loop with a hard parser timeout."""
    try:
        async with asyncio.timeout(timeout_s):
            return await asyncio.to_thread(analyze_wav, path, config)
    except TimeoutError as exc:
        raise ValueError("audio decode timed out") from exc


def config_from_yaml(path: Path) -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
