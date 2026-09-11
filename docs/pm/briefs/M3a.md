# Brief: M3a Audio sources (M3.1–M3.5)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium

## Goal
Implement the audio source layer: one protocol and four sources. Every source yields **mono float32 at 16 kHz with monotonic stream timestamps**, ready to feed `tonewatch.dsp.engine.DetectionEngine`. Work test-first. M3.6–M3.7 (pipeline, supervisor, watchdog) are a separate brief. Don't start them.

Before starting, read `AGENTS.md`, `PLAN.md` (Architecture, M3), `docs/PROGRESS.md`, `backend/src/tonewatch/config/models.py` (the `Source` union), `backend/src/tonewatch/dsp/engine.py`, and `docs/benchmarks.md` (the `analyze` I/O conventions).

## In scope
M3.1, M3.2, M3.3, M3.4, M3.5.

## Required design
- **`sources/base.py`**
  - `AudioFrame(samples: NDArray[float32], stream_time_s: float, source_id: str)`, frozen. `stream_time_s` is the time of the **first sample**, computed from samples delivered, **never the wall clock**, so it is deterministic in tests.
  - `class AudioSource(Protocol)` with `async open()`, `async close()` and `__aiter__` yielding `AudioFrame`, plus `async with` support.
  - A `SourceError` hierarchy: `SourceUnavailable` (retryable) vs `SourceConfigError` (not retryable).
  - A shared resampler helper that converts any rate or channel count to mono float32 16 kHz. Put it in `sources/resample.py`, reuse the M2.7 WAV resampling code rather than duplicating it, and cover it with a property test (duration preserved within one sample; a 1 kHz tone keeps its frequency).
  - `make_source(config: Source) -> AudioSource` factory.
- **`file.py` (M3.2):** WAV, plus any format PyAV decodes. `realtime=True` paces chunks to wall time (use an injectable clock/sleep so tests don't actually sleep), `realtime=False` delivers as fast as possible, and `loop=True` restarts at EOF while stream time keeps increasing. Chunk size is configurable (default 1600 samples).
- **`soundcard.py` (M3.3):**
  - Use a `sounddevice.InputStream` callback that pushes into an `asyncio.Queue` via `loop.call_soon_threadsafe`. The queue is bounded, and overflow drops the oldest data, counts it, and logs a warning.
  - Device selection by index or case-insensitive name substring. Channel select `left|right|mix`.
  - Open at the device's native rate, then resample.
  - `tonewatch devices` CLI lists input devices (index, name, host API, max input channels, default rate), with a `--json` option.
  - Tests **mock `sounddevice`**; no audio hardware exists in CI. Drive the callback from a real `threading.Thread`.
  - **Carry-over from M1 (required):** add a test proving `EventBus.publish` called from a non-async thread delivers through `call_soon_threadsafe`. Today `events.py` lines 89–92 are untested.
- **`stream.py` (M3.4):**
  - PyAV decode of HTTP/Icecast/RTSP URLs, with reconnect using exponential backoff (1 s → 60 s cap, with jitter). An injectable sleep lets tests skip the waiting.
  - Stream time **continues across reconnects**, and a gap marker records the lost duration: add `AudioFrame.discontinuity: bool` set on the first frame after a reconnect.
  - **Integration test:** no ffmpeg binary is available. Generate an MP3 or Ogg file with PyAV (proven in M0.6) and serve it from a local `http.server` thread on 127.0.0.1 with an ephemeral port. Assert that decoded audio matches, and that a mid-stream server shutdown followed by restart triggers reconnect and a discontinuity flag.
- **`rtlsdr.py` (M3.5):**
  - Build the argv for `rtl_fm -f <freq> -M fm -s <rate> -r 16000 -g <gain> -p <ppm> -l <squelch> -` as a list, and **never use a shell**.
  - Read s16le from stdout as float32. Restart on process exit with backoff. On close, kill the process and reap it; no zombies.
  - The `rtl_fm` executable path is configurable. A missing binary raises `SourceConfigError` with a clear message.
  - **Test with a fake `rtl_fm`:** a small Python script invoked through `sys.executable` that writes a known s16le tone to stdout and then exits, to exercise restart. Assert the argv and that there's no shell.

## Constraints
- Nothing blocks the event loop. The sounddevice callback and the subprocess reading must not stall asyncio: use `asyncio.create_subprocess_exec` for rtl_fm, and PyAV decode in `asyncio.to_thread`.
- Keep ≥85% overall coverage. Aim for ≥90% on `sources/`, since the pipeline builds on it.
- The Linux CI runner has PortAudio installed via apt (see `ci.yml`), but **no** audio devices. Tests must not require a device on any OS.
- New dependencies go through `uv add --project backend` and must pass the license policy (no GPL or AGPL).

## Definition of done
- `just check` exits 0.
- pre-commit over all files exits 0 with no unexpected skips (use `pre-commit run --files` over `git ls-files -co --exclude-standard`; `git add` is denied in the sandbox).
- `docs/PROGRESS.md` ticks M3.1–M3.5.
- The final message covers:
  - per task ID, what changed and how it was verified
  - the `tonewatch devices` output on this machine (it has real input devices, so run it)
  - deviations and risks
  - unfiltered tails of the verification commands
