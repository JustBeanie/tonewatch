# ADR 0011: incremental live MP3 encoding

## Decision

ToneWatch encodes normalized mono float32 frames with PyAV's `AudioResampler`
from 16 kHz to 44.1 kHz, then sends packets from a 44.1 kHz MP3 stream at a
constant 48 kbps (configurable within the live-stream bitrate bounds). Packets
are emitted incrementally and concatenated for each listener; the stream is
flushed when the last listener leaves.

## Spike finding

`backend/tests/spike/test_live_encoding.py` passed on the development host:
twenty 100 ms frames were accepted incrementally, their concatenated packet
bytes decoded with PyAV, and the decoded sample count covered the input after
the normal encoder delay. A 100-frame host measurement reported **0.928 ms
p50**, **1.501 ms p95**, and **7.437 ms maximum** wall-clock encoder time per
100 ms frame (single listener, 48 kbps). This is below the few-millisecond
target at p50/p95; the occasional maximum is bounded by the synchronous
per-frame call and is visible to the existing channel yield boundary.

The MP3 encoder adds one frame of codec priming (approximately 26 ms at 44.1
kHz) before the first decodable audio and a final flush tail. Therefore live
listeners receive the first packet after the encoder's normal priming buffer,
not after an entire source recording is accumulated.

## Consequences

The live hub keeps encoding work off the event loop when needed and treats MP3
packets as opaque chunks. No container header is required for the browser and
HA-compatible elementary MP3 response.
