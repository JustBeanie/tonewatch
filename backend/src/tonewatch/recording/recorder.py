"""Streaming call assembly and tonal-span trimming."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING

import numpy as np

from tonewatch.events import CallClosed, EventBus, RecordingReady

if TYPE_CHECKING:
    from tonewatch.config.models import RecordingPolicy, ToneSet
    from tonewatch.dsp.engine import EngineOutput
    from tonewatch.pipeline.channel import RecorderCall
    from tonewatch.pipeline.ringbuffer import RingBuffer
    from tonewatch.recording.encoder import AudioEncoder, EncodedRecording
    from tonewatch.sources.base import AudioFrame


@dataclass(frozen=True, slots=True)
class RecordingResult:
    call_id: str
    files: tuple[EncodedRecording, ...]


class CallRecorder:
    """Collect one open call and encode it after its lifecycle closes."""

    def __init__(
        self,
        tonesets: list[ToneSet] | tuple[ToneSet, ...],
        encoder: AudioEncoder,
        *,
        bus: EventBus | None = None,
    ) -> None:
        self.tonesets = {tone.id: tone for tone in tonesets}
        self.encoder = encoder
        self.bus = bus
        self.logger = logging.getLogger(__name__)
        self.samples: list[np.ndarray] = []
        self.start_s: float | None = None
        self.last_detection_s: float | None = None
        self.max_s = 0.0
        self.post_s = 0.0
        self.silence_stop_s = 0.0
        self.formats: set[str] = set()
        self.spans: list[tuple[float, float]] = []
        self.call: RecorderCall | None = None
        self._silence_s = 0.0
        self._captured_end_s = 0.0
        self._hit_cap = False

    async def __call__(
        self,
        frame: AudioFrame,
        ring: RingBuffer,
        output: EngineOutput,
        call: RecorderCall | None,
        lifecycle: str,
    ) -> None:
        """Adapt the recorder to the channel's typed asynchronous hook."""
        self.process(frame, ring, output, call, lifecycle)

    def process(
        self,
        frame: AudioFrame,
        ring: RingBuffer,
        output: EngineOutput,
        call: RecorderCall | None,
        lifecycle: str = "active",
    ) -> None:
        del lifecycle
        if call is not None and self.call is None:
            self.call = call
            policy = self._policy(call.toneset_ids)
            pre = max(
                (self.tonesets[item].record.pre_roll_s for item in call.toneset_ids), default=0
            )
            all_values, all_start = ring.snapshot_with_time()
            first_tone = min(
                (segment.start_s for segment in output.segments), default=frame.stream_time_s
            )
            desired_start = first_tone - pre
            if all_start is None:
                values, start = all_values, frame.stream_time_s
            else:
                left = max(0, round((desired_start - all_start) * 16_000))
                values = all_values[left:]
                start = all_start + left / 16_000
            self.samples = [values] if values.size else []
            self.start_s = start if start is not None else frame.stream_time_s
            self._captured_end_s = ring.end_stream_time_s or frame.stream_time_s
            self.last_detection_s = frame.stream_time_s
            self.max_s = policy.max_s
            self.post_s = policy.post_s
            self.silence_stop_s = policy.silence_stop_s
            self.formats = set(policy.formats)
        if call is None or self.call is None:
            return
        if call.toneset_ids != self.call.toneset_ids:
            self.call = call
            policy = self._policy(call.toneset_ids)
            self.max_s = max(self.max_s, policy.max_s)
            self.post_s = max(self.post_s, policy.post_s)
            self.silence_stop_s = max(self.silence_stop_s, policy.silence_stop_s)
            self.formats.update(policy.formats)
            self.last_detection_s = frame.stream_time_s
        if output.detections:
            self.last_detection_s = max(item.detected_at_s for item in output.detections)
        self.spans.extend((segment.start_s, segment.end_s) for segment in output.segments)
        if self.start_s is not None and frame.stream_time_s >= self._captured_end_s - 1e-6:
            frame_end = frame.stream_time_s + frame.samples.size / 16_000
            elapsed = frame_end - self.start_s
            remaining = max(0, round((self.max_s - elapsed) * 16_000))
            if remaining:
                self.samples.append(np.asarray(frame.samples[:remaining], dtype=np.float32).copy())
                self._captured_end_s = frame_end
            else:
                self._hit_cap = True

    def _policy(self, ids: frozenset[str]) -> RecordingPolicy:
        policies = [self.tonesets[item].record for item in ids if item in self.tonesets]
        if not policies:
            raise ValueError("call has no configured tone sets")
        first = policies[0]
        return first.model_copy(
            update={
                "pre_roll_s": max(item.pre_roll_s for item in policies),
                "post_s": max(item.post_s for item in policies),
                "silence_stop_s": max(item.silence_stop_s for item in policies),
                "max_s": max(item.max_s for item in policies),
                "formats": sorted({fmt for item in policies for fmt in item.formats}),
            }
        )

    def should_stop(self, stream_end_s: float, samples: np.ndarray | None = None) -> bool:
        """Return whether post-roll, silence, or the hard cap has been reached."""
        if self.start_s is None or self.last_detection_s is None:
            return False
        if stream_end_s - self.start_s >= self.max_s:
            return True
        if stream_end_s - self.last_detection_s >= self.post_s:
            return True
        if samples is not None and samples.size:
            rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
            self._silence_s = (
                self._silence_s + samples.size / 16_000 if rms < 10 ** (-50 / 20) else 0.0
            )
        return self._silence_s >= self.silence_stop_s

    def _trim(self) -> np.ndarray:
        raw = np.concatenate(self.samples) if self.samples else np.zeros(0, dtype=np.float32)
        if self.start_s is None or not self.spans:
            return raw
        cuts = sorted(
            (
                max(0, round((start - self.start_s - 0.05) * 16_000)),
                min(raw.size, round((end - self.start_s + 0.05) * 16_000)),
            )
            for start, end in self.spans
        )
        merged: list[list[int]] = []
        for left, right in cuts:
            if right <= left:
                continue
            if merged and left <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], right)
            else:
                merged.append([left, right])
        pieces: list[np.ndarray] = []
        cursor = 0
        for left, right in merged:
            pieces.append(raw[cursor:left])
            cursor = right
        pieces.append(raw[cursor:])
        result = np.concatenate(pieces) if pieces else raw
        offset = 0
        for piece in pieces[:-1]:
            offset += piece.size
            width = min(160, offset, result.size - offset)
            if width:
                result[offset - width : offset] *= np.linspace(1, 0, width, dtype=np.float32)
                result[offset : offset + width] *= np.linspace(0, 1, width, dtype=np.float32)
        if self._hit_cap:
            target = round(self.max_s * 16_000)
            result = np.pad(result[:target], (0, max(0, target - result.size)))
        return result

    async def finish(self) -> RecordingResult | None:
        if self.call is None:
            return None
        call = self.call
        cancelled = False
        try:
            samples = self._trim()
            start = call.started_at.astimezone(UTC)
            title = f"{', '.join(sorted(call.toneset_ids))} {start.isoformat()}"
            encode_task = asyncio.create_task(
                self.encoder.encode(
                    samples,
                    call_id=str(call.id),
                    call_start=start,
                    formats=self.formats,
                    title=title,
                    toneset_ids=call.toneset_ids,
                    source_id=call.source_id,
                ),
                name=f"tonewatch-encode-{call.id}",
            )
            try:
                files = await asyncio.shield(encode_task)
            except asyncio.CancelledError:
                files = await encode_task
                cancelled = True
        except Exception:
            self.logger.exception("recording encoding failed", extra={"call_id": str(call.id)})
            if self.bus is not None:
                self.bus.publish(CallClosed(call.id, "failed", call.source_id))
            self._reset()
            raise
        if self.bus is not None:
            for item in files:
                self.bus.publish(
                    RecordingReady(
                        call.id,
                        str(item.path),
                        item.format,
                        call.source_id,
                        call.drill,
                        call.drill,
                        call.drill_keep,
                    )
                )
            self.bus.publish(
                CallClosed(
                    call.id, "recorded", call.source_id, call.drill, call.drill, call.drill_keep
                )
            )
        result = RecordingResult(str(call.id), tuple(files))
        self._reset()
        if cancelled:
            raise asyncio.CancelledError
        return result

    def _reset(self) -> None:
        """Clear one completed call so the channel can record its next call."""
        self.samples = []
        self.start_s = None
        self.last_detection_s = None
        self.max_s = 0.0
        self.post_s = 0.0
        self.silence_stop_s = 0.0
        self.formats = set()
        self.spans = []
        self.call = None
        self._silence_s = 0.0
        self._captured_end_s = 0.0
        self._hit_cap = False
