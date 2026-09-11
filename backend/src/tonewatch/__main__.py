"""Command-line entry point for ToneWatch."""

import argparse
import json
import wave
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from tonewatch import __version__
from tonewatch.config.models import AppConfig
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.sources.soundcard import input_devices


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    values: Any
    if sample_width == 1:
        values = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        values = (values - 128) / 128
    elif sample_width == 2:
        values = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768
    elif sample_width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        values = (
            raw[:, 0].astype(np.int32)
            | (raw[:, 1].astype(np.int32) << 8)
            | (raw[:, 2].astype(np.int32) << 16)
        )
        values = ((values ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
    elif sample_width == 4:
        values = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648
    else:
        raise ValueError(f"unsupported WAV sample width: {sample_width}")
    mono = values.reshape(-1, channels).mean(axis=1).astype(np.float32)
    if sample_rate == 16_000:
        return mono, sample_rate
    target_count = round(mono.size * 16_000 / sample_rate)
    source_time = np.arange(mono.size, dtype=np.float64) / sample_rate
    target_time = np.arange(target_count, dtype=np.float64) / 16_000
    return np.interp(target_time, source_time, mono).astype(np.float32), 16_000


def _json_output(output: Any, include_frames: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema_version": 1, "segments": [], "detections": []}
    if include_frames:
        payload["frames"] = [
            {
                "t_end_s": frame.t_end_s,
                "freq_hz": frame.freq_hz,
                "level_dbfs": frame.level_dbfs,
                "purity": frame.purity,
                "tonal": frame.tonal,
            }
            for frame in output.frames
        ]
    payload["segments"] = [
        {
            "freq_hz": segment.freq_hz,
            "start_s": segment.start_s,
            "end_s": segment.end_s,
            "mean_purity": segment.mean_purity,
            "closed": segment.closed,
            "excess_s": segment.excess_s,
        }
        for segment in output.segments
    ]
    payload["detections"] = [
        {
            "toneset_id": detection.toneset_id,
            "detected_at_s": detection.detected_at_s,
            "early": detection.early,
            "segments": [
                {
                    "freq_hz": segment.freq_hz,
                    "start_s": segment.start_s,
                    "end_s": segment.end_s,
                    "excess_s": segment.excess_s,
                }
                for segment in detection.segments
            ],
        }
        for detection in output.detections
    ]
    return payload


def _analyze(args: argparse.Namespace) -> None:
    raw_config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    config = AppConfig.model_validate(raw_config)
    samples, _ = _read_wav(args.file)
    output = DetectionEngine(config.tone_sets).feed(samples)
    payload = _json_output(output, args.frames)
    if args.json:
        json.dump(payload, fp=__import__("sys").stdout, indent=2)
        __import__("sys").stdout.write("\n")
        return
    __import__("sys").stdout.write("Segments\n")
    __import__("sys").stdout.write("freq_hz  start_s  end_s  purity  closed\n")
    for segment in payload["segments"]:
        __import__("sys").stdout.write(
            f"{segment['freq_hz']:7.1f} {segment['start_s']:8.2f} {segment['end_s']:6.2f} "
            f"{segment['mean_purity']:.3f} {segment['closed']}\n"
        )
    __import__("sys").stdout.write("Detections\n")
    for detection in payload["detections"]:
        __import__("sys").stdout.write(
            f"{detection['toneset_id']} at {detection['detected_at_s']:.2f}s "
            f"(early={detection['early']})\n"
        )
    if args.frames:
        __import__("sys").stdout.write(f"Frames: {len(payload.get('frames', []))}\n")


def _devices(args: argparse.Namespace) -> None:
    """List available input devices."""
    devices = input_devices()
    if args.json:
        json.dump(devices, fp=__import__("sys").stdout, indent=2)
        __import__("sys").stdout.write("\n")
        return
    __import__("sys").stdout.write("index  name  host_api  max_input_channels  default_rate\n")
    for device in devices:
        __import__("sys").stdout.write(
            f"{device['index']:5}  {device['name']}  {device['host_api']}  "
            f"{device['max_input_channels']:18}  {device['default_rate']:12g}\n"
        )


def _serve(_args: argparse.Namespace) -> None:
    """Start the authenticated HTTP service."""
    import uvicorn
    from tonewatch.api.app import create_app
    from tonewatch.logging import configure_logging
    from tonewatch.settings import Settings

    settings = Settings.load()
    configure_logging(settings.log_level, json=True)
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.bind_port)


def _token(args: argparse.Namespace) -> None:
    """Show or rotate the API token."""
    from tonewatch.api.auth import read_or_create_token, rotate_token
    from tonewatch.settings import Settings

    settings = Settings.load()
    import sys

    sys.stdout.write(
        (read_or_create_token(settings) if args.action == "show" else rotate_token(settings)) + "\n"
    )


def main() -> None:
    """Run the ToneWatch command-line interface."""
    parser = argparse.ArgumentParser(prog="tonewatch")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("file", type=Path)
    analyze.add_argument("--config", required=True, type=Path)
    analyze.add_argument("--json", action="store_true")
    analyze.add_argument("--frames", action="store_true")
    devices = subparsers.add_parser("devices")
    devices.add_argument("--json", action="store_true")
    subparsers.add_parser("serve")
    token = subparsers.add_parser("token")
    token.add_argument("action", choices=("show", "rotate"))
    args = parser.parse_args()
    if args.command == "analyze":
        _analyze(args)
    elif args.command == "devices":
        _devices(args)
    elif args.command == "serve":
        _serve(args)
    elif args.command == "token":
        _token(args)


if __name__ == "__main__":
    main()
