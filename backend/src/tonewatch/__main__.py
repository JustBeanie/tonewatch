"""Command-line entry point for ToneWatch."""

import argparse
import importlib
import json
import pkgutil
import sys
import wave
from pathlib import Path
from typing import Any, cast

import numpy as np
import yaml

import tonewatch
from tonewatch import __version__
from tonewatch.config.models import AppConfig
from tonewatch.config.store import ConfigStore
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.dsp.discovery import DiscoveryTracker
from tonewatch.importers.tones_cfg import (
    TonesCfgImportError,
    apply_tones_cfg,
    parse_tones_cfg,
)
from tonewatch.sources.soundcard import input_devices

UVICORN_SECURITY_OPTIONS = {
    "timeout_keep_alive": 5,
    "h11_max_incomplete_event_size": 64 * 1024,
    "limit_concurrency": 100,
}


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
    engine = DetectionEngine(config.tone_sets)
    output = engine.feed(samples)
    discovered: list[Any] = []
    if getattr(args, "discover", False):
        tracker = DiscoveryTracker(
            max_gap_s=config.discovery.max_gap_s,
            min_segment_s=config.discovery.min_segment_s,
            max_segment_s=config.discovery.max_segment_s,
        )
        discovered = tracker.feed(
            output.segment_update,
            output.detections,
            samples.size / 16_000,
        )
        flush = engine.feed(
            np.zeros(round((config.discovery.max_gap_s + 0.5) * 16_000), dtype=np.float32)
        )
        discovered.extend(
            tracker.feed(
                flush.segment_update,
                flush.detections,
                samples.size / 16_000 + config.discovery.max_gap_s + 0.5,
            )
        )
    payload = _json_output(output, args.frames)
    payload["discovered"] = [
        {
            "frequencies": list(candidate.frequencies),
            "durations": list(candidate.durations),
            "start_s": candidate.start_s,
            "end_s": candidate.end_s,
            "mean_purity": candidate.mean_purity,
        }
        for candidate in discovered
    ]
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
    if getattr(args, "discover", False):
        __import__("sys").stdout.write("Discovered tones\n")
        __import__("sys").stdout.write("frequencies  durations  start_s  end_s\n")
        for candidate in payload["discovered"]:
            __import__("sys").stdout.write(
                f"{'/'.join(f'{value:g}' for value in candidate['frequencies'])}  "
                f"{'/'.join(f'{value:.2f}' for value in candidate['durations'])}  "
                f"{candidate['start_s']:.2f}  {candidate['end_s']:.2f}\n"
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
    uvicorn.run(
        create_app(settings),
        host=settings.bind_host,
        port=settings.bind_port,
        **cast("Any", UVICORN_SECURITY_OPTIONS),
    )


def _token(args: argparse.Namespace) -> None:
    """Show or rotate the API token."""
    from tonewatch.api.auth import read_or_create_token, rotate_token
    from tonewatch.settings import Settings

    settings = Settings.load()
    import sys

    sys.stdout.write(
        (read_or_create_token(settings) if args.action == "show" else rotate_token(settings)) + "\n"
    )


def _selftest_imports(_args: argparse.Namespace) -> None:
    """Import every discoverable ToneWatch module in the running distribution."""
    modules = [tonewatch.__name__]
    modules.extend(
        module.name for module in pkgutil.walk_packages(tonewatch.__path__, "tonewatch.")
    )
    failures: list[str] = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as error:
            failures.append(f"{name}: {error}")
    if failures:
        for failure in failures:
            sys.stderr.write(f"import failed: {failure}\n")
        raise SystemExit(1)
    sys.stdout.write(f"imported {len(modules)} tonewatch modules\n")


def _selftest_https(args: argparse.Namespace) -> None:
    """Verify the product PyAV HTTPS options through the frozen executable."""
    import av
    import certifi
    from av.error import InvalidDataError

    options = {"tls_verify": "1", "ca_file": certifi.where()}
    try:
        container = av.open(args.url, options=options)
    except InvalidDataError:
        sys.stdout.write("HTTPS certificate verification passed\n")
        return
    container.close()
    raise SystemExit("expected InvalidDataError after successful HTTPS handshake")


def _service(args: argparse.Namespace) -> None:
    """Run a Windows service command."""
    from tonewatch.service import run_command
    from tonewatch.settings import Settings

    code = run_command(args.action, data_dir=args.data_dir or Settings.load().data_dir)
    if code:
        raise SystemExit(code)


def _checkpoint(_args: argparse.Namespace) -> None:
    """Checkpoint the live SQLite WAL for a hot backup."""
    import sys

    from tonewatch.settings import Settings
    from tonewatch.storage.db import DatabaseCheckpointError, checkpoint_database

    settings = Settings.load()
    try:
        checkpoint_database(settings.data_dir / "tonewatch.db")
    except DatabaseCheckpointError as exc:
        raise SystemExit(str(exc)) from exc
    sys.stdout.write("database checkpoint complete\n")


def _import_tones_cfg(args: argparse.Namespace) -> None:
    """Preview or apply a legacy tones.cfg configuration."""
    import sys

    try:
        text = args.path.read_bytes().decode("utf-8")
        result = parse_tones_cfg(text)
    except (OSError, UnicodeDecodeError, TonesCfgImportError) as exc:
        sys.stderr.write(f"could not import tones.cfg: {exc}\n")
        raise SystemExit(2) from exc
    if args.apply and result.tone_sets:
        from tonewatch.settings import Settings

        try:
            store = ConfigStore(Settings.load().data_dir)
            config = apply_tones_cfg(store.load(), result, args.mode)
            store.save(config)
        except (OSError, TonesCfgImportError) as exc:
            sys.stderr.write(f"could not apply tones.cfg: {exc}\n")
            raise SystemExit(2) from exc
    if args.json:
        payload = result.as_dict()
        payload["applied"] = bool(args.apply and result.tone_sets)
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write("tones.cfg import preview\n")
        sys.stdout.write(f"{result.imported_count} imported, {result.skipped_count} skipped\n")
        for section in result.sections:
            status = "imported" if section.imported else "skipped"
            details = ""
            if section.tone_set is not None:
                details = ", ".join(
                    f"{tone.freq_hz:g} Hz/{tone.min_s:g} s" for tone in section.tone_set.sequence
                )
            sys.stdout.write(f"{status}: {section.name}{(': ' + details) if details else ''}\n")
            for note in section.notes:
                sys.stdout.write(f"  note: {note}\n")
            for error in section.errors:
                sys.stdout.write(f"  error: {error}\n")
    if not result.tone_sets:
        raise SystemExit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tonewatch")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("file", type=Path)
    analyze.add_argument("--config", required=True, type=Path)
    analyze.add_argument("--json", action="store_true")
    analyze.add_argument("--frames", action="store_true")
    analyze.add_argument("--discover", action="store_true")
    devices = subparsers.add_parser("devices")
    devices.add_argument("--json", action="store_true")
    subparsers.add_parser("serve")
    token = subparsers.add_parser("token")
    token.add_argument("action", choices=("show", "rotate"))
    service = subparsers.add_parser("service")
    service.add_argument("action", choices=("install", "uninstall", "start", "stop", "status"))
    service.add_argument("--data-dir", type=Path)
    service_run = subparsers.add_parser("service-run", help=argparse.SUPPRESS)
    service_run.add_argument("--data-dir", required=True, type=Path)
    selftest = subparsers.add_parser("selftest")
    selftest.add_argument("action", choices=("imports", "https"))
    selftest.add_argument("url", nargs="?", default="https://github.com")
    db = subparsers.add_parser("db")
    db_subparsers = db.add_subparsers(dest="db_command", required=True)
    db_subparsers.add_parser("checkpoint")
    importer = subparsers.add_parser("import")
    tones_cfg = importer.add_subparsers(dest="importer", required=True).add_parser("tones-cfg")
    tones_cfg.add_argument("path", type=Path)
    tones_cfg.add_argument("--apply", action="store_true")
    tones_cfg.add_argument("--mode", choices=("merge", "replace"), default="merge")
    tones_cfg.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    """Run the ToneWatch command-line interface."""
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "analyze":
        _analyze(args)
    elif args.command == "devices":
        _devices(args)
    elif args.command == "serve":
        _serve(args)
    elif args.command == "token":
        _token(args)
    elif args.command == "service":
        _service(args)
    elif args.command == "selftest":
        if args.action == "imports":
            _selftest_imports(args)
        else:
            _selftest_https(args)
    elif args.command == "service-run":
        from tonewatch.service import run_service_process

        run_service_process(args.data_dir)
    elif args.command == "db" and args.db_command == "checkpoint":
        _checkpoint(args)
    elif args.command == "import" and args.importer == "tones-cfg":
        _import_tones_cfg(args)


if __name__ == "__main__":
    main()
