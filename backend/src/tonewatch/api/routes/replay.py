"""Authenticated, non-persistent replay of audio against a draft configuration."""

from __future__ import annotations

import asyncio
import os
import secrets
import time
import wave
from pathlib import Path
from typing import Any, cast

import av
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import ValidationError
from sqlalchemy import select

from tonewatch.__main__ import _read_wav
from tonewatch.api.audit import SecretRestoreError, record_audit, restore_secrets
from tonewatch.api.deps import authenticated
from tonewatch.config.models import AppConfig
from tonewatch.dsp.engine import DetectionEngine
from tonewatch.recording.retention import safe_recording_path
from tonewatch.storage.models import Call, CallToneSet, Recording

router = APIRouter(prefix="/api/admin/replay", tags=["admin-replay"])
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_AUDIO_SECONDS = 600.0
UPLOAD_TTL_SECONDS = 3600.0
REPLAY_TIMEOUT_SECONDS = 10.0


def classify_replay(
    item_id: str,
    actual: list[str] | None,
    draft: list[str],
    *,
    unchanged_label: str = "would_detect",
) -> dict[str, Any]:
    actual_ids = actual or []
    actual_set, draft_set = set(actual_ids), set(draft)
    if actual_set == draft_set:
        classification = unchanged_label
    elif actual_set - draft_set:
        classification = "would_miss"
    else:
        classification = "new_detection"
    return {"id": item_id, "actual": actual, "draft": draft, "classification": classification}


def summarize_replay(items: list[dict[str, Any]]) -> dict[str, int]:
    """Count each stable replay classification, including skipped items."""
    return {
        name: sum(item.get("classification") == name for item in items)
        for name in ("would_detect", "would_miss", "new_detection", "unchanged", "skipped")
    }


def _upload_dir(request: Request) -> Path:
    path = request.app.state.settings.data_dir / "replay-uploads"
    path.mkdir(parents=True, exist_ok=True)
    return cast("Path", path)


def _clean_uploads(directory: Path, *, now: float | None = None) -> None:
    cutoff = (time.time() if now is None else now) - UPLOAD_TTL_SECONDS
    for path in directory.glob("*.wav"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except OSError:
            continue


def _decode_audio(path: Path) -> tuple[np.ndarray, float]:
    if path.suffix.casefold() == ".wav":
        samples, _ = _read_wav(path)
        return samples, samples.size / 16_000
    with av.open(str(path), mode="r") as container:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        audio_stream = cast("Any", stream)
        if audio_stream is None or not audio_stream.rate:
            raise ValueError("recording has no decodable audio stream")
        chunks: list[np.ndarray] = []
        for frame in container.decode(stream):
            values = cast("Any", frame).to_ndarray()
            if values.ndim == 2:
                values = values.mean(axis=0)
            if np.issubdtype(values.dtype, np.integer):
                values = values.astype(np.float32) / max(abs(np.iinfo(values.dtype).min), 1)
            chunks.append(np.asarray(values, dtype=np.float32))
        source = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        if audio_stream.rate == 16_000:
            samples = source
        else:
            target_count = round(source.size * 16_000 / audio_stream.rate)
            source_time = np.arange(source.size, dtype=np.float64) / audio_stream.rate
            target_time = np.arange(target_count, dtype=np.float64) / 16_000
            samples = np.interp(target_time, source_time, source).astype(np.float32)
        return samples, samples.size / 16_000


def _draft_config(current: AppConfig, draft: Any) -> tuple[AppConfig, dict[str, Any]]:
    if not isinstance(draft, dict):
        raise HTTPException(422, "draft must be an object")
    tuning = draft.get("tuning", {})
    if not isinstance(tuning, dict):
        raise HTTPException(422, "tuning must be an object")
    submitted = {key: value for key, value in draft.items() if key != "tuning"}
    stored = current.model_dump(mode="python")
    raw = dict(stored)
    raw.update(submitted)
    try:
        return AppConfig.model_validate(restore_secrets(stored, raw)), tuning
    except (SecretRestoreError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from None


async def _run_detection(
    path: Path, config: AppConfig, tuning: dict[str, Any]
) -> tuple[list[dict[str, Any]], float]:
    async with asyncio.timeout(REPLAY_TIMEOUT_SECONDS):
        samples, duration = await asyncio.to_thread(_decode_audio, path)
        output = await asyncio.to_thread(DetectionEngine(config.tone_sets, **tuning).feed, samples)
    grouped: dict[str, list[float]] = {}
    for detection in output.detections:
        grouped.setdefault(detection.toneset_id, []).append(detection.detected_at_s)
    return [
        {"toneset_id": key, "detection_times": times} for key, times in grouped.items()
    ], duration


async def _recording_items(
    request: Request, last_n: int
) -> list[tuple[str, Path | None, list[str]]]:
    async with request.app.state.session_factory() as session:
        calls = list(
            (
                await session.scalars(select(Call).order_by(Call.started_at.desc()).limit(last_n))
            ).all()
        )
        result: list[tuple[str, Path | None, list[str]]] = []
        for call in calls:
            actual = list(
                (
                    await session.scalars(select(CallToneSet).where(CallToneSet.call_id == call.id))
                ).all()
            )
            recordings = list(
                (await session.scalars(select(Recording).where(Recording.call_id == call.id))).all()
            )
            for recording in recordings:
                try:
                    path = safe_recording_path(
                        request.app.state.settings.recording_path, Path(recording.path)
                    )
                except ValueError:
                    result.append((f"recording-{recording.id}", None, ["__skipped_outside_root__"]))
                    continue
                result.append(
                    (f"recording-{recording.id}", path, [row.toneset_id for row in actual])
                )
        return result


@router.post("/uploads", dependencies=[Depends(authenticated)])
async def upload_replay_wav(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    directory = _upload_dir(request)
    _clean_uploads(directory, now=request.app.state.auth.clock())
    upload_id = secrets.token_urlsafe(18)
    path = directory / f"{upload_id}.wav"
    size = 0
    try:
        with path.open("xb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "upload too large")
                handle.write(chunk)
        try:
            with wave.open(str(path), "rb") as source:
                duration = source.getnframes() / source.getframerate()
                if duration > 600:
                    raise HTTPException(413, "audio too long")
        except HTTPException:
            raise
        except (wave.Error, EOFError, ZeroDivisionError):
            raise HTTPException(422, "expected RIFF/WAVE audio") from None
        now = request.app.state.auth.clock()
        os.utime(path, (now, now))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"id": upload_id, "expires_in_s": UPLOAD_TTL_SECONDS, "size_bytes": size}


@router.post("", dependencies=[Depends(authenticated)])
async def replay(request: Request) -> dict[str, Any]:
    if getattr(request.app.state, "replay_active", False):
        raise HTTPException(429, "replay already in progress")
    lock = getattr(request.app.state, "replay_lock", None)
    if lock is None:
        lock = request.app.state.replay_lock = asyncio.Lock()
    request.app.state.replay_active = True
    async with lock:
        try:
            body = await request.json()
            draft, tuning = _draft_config(request.app.state.config, body.get("draft"))
            calls = body.get("calls")
            uploads = body.get("uploads")
            if calls is None and uploads is None:
                raise HTTPException(422, "calls or uploads is required")
            if calls is not None and (
                not isinstance(calls, dict)
                or not isinstance(calls.get("last_n"), int)
                or not 1 <= calls["last_n"] <= 50
            ):
                raise HTTPException(422, "calls.last_n must be between 1 and 50")
            if uploads is not None and (
                not isinstance(uploads, list) or not all(isinstance(item, str) for item in uploads)
            ):
                raise HTTPException(422, "uploads must be an array of ids")
            items = await _recording_items(request, calls["last_n"]) if calls else []
            directory = _upload_dir(request)
            _clean_uploads(directory, now=request.app.state.auth.clock())
            for upload_id in uploads or []:
                if (
                    "/" in upload_id
                    or "\\" in upload_id
                    or ".." in upload_id
                    or not (directory / f"{upload_id}.wav").is_file()
                ):
                    raise HTTPException(404, "replay upload not found")
                items.append((f"upload-{upload_id}", directory / f"{upload_id}.wav", []))
            total = 0.0
            output: list[dict[str, Any]] = []
            for item_id, path, actual in items:
                if path is None:
                    output.append(
                        {
                            "id": item_id,
                            "actual": None,
                            "recorded": None if item_id.startswith("upload-") else actual,
                            "draft": [],
                            "classification": "skipped",
                            "reason": "recording outside root",
                        }
                    )
                    continue
                try:
                    _, duration = await asyncio.to_thread(_decode_audio, path)
                    if total + duration > MAX_AUDIO_SECONDS:
                        output.append(
                            {
                                "id": item_id,
                                "actual": None if item_id.startswith("upload-") else actual,
                                "recorded": None if item_id.startswith("upload-") else actual,
                                "draft": [],
                                "classification": "skipped",
                                "reason": "total audio cap exceeded",
                            }
                        )
                        continue
                    total += duration
                    baseline, _ = await _run_detection(path, request.app.state.config, {})
                    baseline_actual = [item["toneset_id"] for item in baseline]
                    detected, _ = await _run_detection(path, draft, tuning)
                except (OSError, ValueError, TimeoutError) as exc:
                    output.append(
                        {
                            "id": item_id,
                            "actual": None if item_id.startswith("upload-") else actual,
                            "recorded": None if item_id.startswith("upload-") else actual,
                            "draft": [],
                            "classification": "skipped",
                            "reason": str(exc),
                        }
                    )
                    continue
                draft_ids = [item["toneset_id"] for item in detected]
                item_actual = None if item_id.startswith("upload-") else baseline_actual
                item = classify_replay(
                    item_id,
                    baseline_actual,
                    draft_ids,
                    unchanged_label="would_detect"
                    if item_id.startswith("upload-")
                    else "unchanged",
                )
                item["actual"] = item_actual
                item["recorded"] = None if item_id.startswith("upload-") else actual
                item["draft"] = detected
                output.append(item)
            summary = summarize_replay(output)
            await record_audit(
                request.app.state.session_factory,
                actor=getattr(request.state, "auth", "unknown"),
                event_type="replay",
                resource="config",
                details={"items": len(output), "audio_seconds": total},
            )
            return {
                "items": output,
                "summary": summary,
                "audio_seconds": total,
                "audio_cap_seconds": MAX_AUDIO_SECONDS,
                "limitations": [
                    "Stored call recordings are tone-trimmed voice clips. "
                    "Replaying them checks that the draft doesn't start triggering "
                    "on voice traffic. "
                    "Use uploaded WAVs to test tone detection.",
                ],
            }
        finally:
            request.app.state.replay_active = False
