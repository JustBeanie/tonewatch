"""Generate the hermetic WAV and file-source configuration used by e2e."""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np
from tonewatch.dsp.generator import concat, silence, tone, voice_like


def _config(source_path: str) -> str:
    """Return the valid fixture page configuration."""
    yaml_source_path = source_path.replace("'", "''")
    return f"""tone_sets:
  - id: fixture-page
    name: Fixture page
    sequence:
      - freq_hz: 1000
        tol_pct: 2
        min_s: 0.8
        max_s: 1.3
      - freq_hz: 1500
        tol_pct: 2
        min_s: 2.5
        max_s: 3.5
    cooldown_s: 0
    record:
      pre_roll_s: 0.2
      post_s: 2
      silence_stop_s: 8
      max_s: 15
      formats: [mp3]
sources:
  - id: fixture-radio
    name: Fixture radio
    type: file
    path: '{yaml_source_path}'
    realtime: true
    loop: true
    tonesets: [fixture-page]
live_stream:
  enabled: true
  bitrate_kbps: 48
  max_listeners_per_source: 4
  max_listeners_total: 12
  token_ttl_s: 3600
  max_lag_s: 10
alert_targets: []
"""


def generate(fixture: Path, config: Path, source_path: str) -> None:
    """Write the deterministic fixture audio and config."""
    fixture.parent.mkdir(parents=True, exist_ok=True)
    config.parent.mkdir(parents=True, exist_ok=True)
    samples = concat(
        silence(0.5),
        tone(1000, 1.0, 0.5),
        silence(0.15),
        tone(1500, 3.0, 0.5),
        voice_like(4.0, seed=17),
    )
    with wave.open(str(fixture), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    config.write_text(_config(source_path), encoding="utf-8")


def main() -> None:
    """Parse paths and generate the e2e fixture."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-path")
    args = parser.parse_args()
    generate(args.fixture, args.config, args.source_path or str(args.fixture))


if __name__ == "__main__":
    main()
