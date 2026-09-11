# Brief: M3b Pipeline, supervisor and watchdog (M3.6–M3.7)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high

## Goal
Connect sources to detection and persistence: per-source channels run concurrently under a supervisor that restarts failed channels, and a watchdog reports feed health. This is the concurrency core, so correctness under failure matters more than features. Work test-first.

Before starting, read `AGENTS.md`, `PLAN.md` (Architecture, M3, Detection design), `docs/PROGRESS.md`, `docs/pm/carryover.md`, and these files: `backend/src/tonewatch/sources/base.py`, `dsp/engine.py`, `events.py`, `storage/repository.py`, `storage/db.py`, `config/models.py`.

## In scope
M3.6, M3.7, and the `storage/db.py` carry-over. **No recording or encoding.** M4 adds the recorder; leave a typed hook for it.

## Required design

### `pipeline/ringbuffer.py`
A fixed-capacity float32 ring buffer holding pre-roll (capacity from the largest `record.pre_roll_s` among the channel's tone sets, default 10 s), with `extend()` and `snapshot(seconds)`. It carries stream-time bookkeeping so M4 can slice by stream time. Add a property test showing that snapshot contents always equal the last N samples written, whatever the chunk sizes.

### `pipeline/channel.py`
`Channel(source_config, tonesets, bus, clock, recorder_hook: RecorderHook | None)`.
- Loop: `async for frame in source` → ringbuffer → `DetectionEngine.feed(frame.samples)` → per detection, publish `ToneDetected`. Pass the current frame and ringbuffer to `recorder_hook` if set.
- **Call grouping (stacked pages):** a detection within `CALL_MERGE_WINDOW_S` (default: the tone set's `record.post_s`) of the channel's open call joins that call (same `call_id`, extra `CallToneSet`). Otherwise it opens a new call. Close the call after the window passes with no new detection, and publish `CallClosed(status="recorded")`. M4 may change the status later.
- **Wall-clock conversion:** detection times are stream seconds. Convert them to UTC with an anchor taken when the channel starts, and re-anchor on `frame.discontinuity`. Keep the clock injectable so tests stay deterministic.
- The only tone sets fed to the engine are those allowed by the source's `tonesets` field (`"all"` or a list of ids) that are also `enabled`.

### `pipeline/supervisor.py`
`Supervisor(config: AppConfig, bus, session_factory, clock, sleep)`.
- `start()` creates one task per enabled source. `stop()` cancels all of them and waits, with a bounded shutdown timeout. `reload(config)` diffs the configs: it stops removed or changed channels and starts new ones, leaving unchanged channels untouched.
- **Restart policy:** `SourceUnavailable` or an unexpected exception restarts the channel with exponential backoff (1 s → 60 s, jitter), and backoff resets after 60 s of healthy running. `SourceConfigError` does **not** restart; mark the channel failed and publish `FeedHealthChanged(healthy=False, reason=...)`.
- One channel crashing must never affect the others. Prove it with a test.
- **Persistence subscriber:** `pipeline/persistence.py` subscribes to the bus and writes `Call` and `CallToneSet` rows through `storage/repository.py`, exercising `storage/db.py` (currently 0% covered, a carry-over). Writes must not block channels; the subscriber has its own task and bounded queue.

### `pipeline/watchdog.py` (M3.7)
- Per channel it checks:
  - **no frames** for more than `no_data_s` (default 10)
  - **flatline**, RMS below −80 dBFS for more than `flatline_s` (default 300)
  - **clipping ratio** above `clip_ratio` (default 0.05 of samples ≥ 0.999) over a 10 s window
  - **disconnect**, i.e. a discontinuity frame or source error
- Publish `FeedHealthChanged` **only on transitions** (healthy→unhealthy with a reason, and back). Add hysteresis so a single good frame doesn't flap the state.
- Clock-driven and testable with an injected clock; no real sleeping in tests.

## Tests
- Unit tests for each component, all with an injected clock and sleep.
- **Integration test (the M3 done-when):** a real temp SQLite DB, run via `storage/db.py` + Alembic upgrade. Two `FileSource` channels in fast mode run concurrently under the Supervisor, each fed a different generated WAV from `dsp/generator.py`. Channel A holds two stacked pages of different tone sets; channel B holds one page plus a later repeat outside cooldown. Assert these DB rows: A = 1 call with 2 `CallToneSet` rows, B = 2 calls. Check the tone set ids and `source_id` too.
- **Restart test:** a source that raises `SourceUnavailable` twice, then works. Assert the backoff delays requested from the injected sleep, and that the channel eventually produces its detection.
- **Isolation test:** channel A crashes permanently with `SourceConfigError`. Channel B still completes, and `FeedHealthChanged(healthy=False)` is published for A.
- **Watchdog tests:** one per condition, plus a hysteresis test.
- Coverage: `pipeline/` ≥95% (already enforced by `check_package_coverage.py`); `storage/db.py` ≥90%.

## Constraints
- No blocking calls on the event loop; DSP `feed` for a 1600-sample chunk is fast (see `docs/benchmarks.md`), so running it inline is fine. Make no `time.sleep` calls; all waiting goes through the injected sleep.
- Every task you create must be awaited or cancelled on `stop()`, so no warnings about pending or never-awaited tasks appear (`pytest -W error` enforces this).
- Don't modify PM-owned files: `scripts/license_check.py`, `.github/workflows/*`, `docs/pm/*`.

## Definition of done
- `just check` exits 0.
- pre-commit over all files exits 0 with no unexpected skips (`pre-commit run --files` over `git ls-files -co --exclude-standard`).
- `docs/PROGRESS.md` ticks M3.6 and M3.7.
- The final message covers:
  - per task ID, what changed and how it was verified
  - coverage for `pipeline/` and `storage/db.py`
  - the integration test's DB assertions
  - deviations and risks
  - unfiltered verification tails
