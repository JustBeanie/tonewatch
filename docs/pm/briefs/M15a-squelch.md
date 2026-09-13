# Brief: M15a — software squelch (backend: M15.1–M15.4)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m15a` (branch `m15a`, based on `origin/main`). **E2E port:** `TONEWATCH_E2E_PORT=8803`.

## Goal
Implement `PLAN.md` M15.1–M15.4: a software squelch for every source type, with state exposed to the API, WS and MQTT/HA discovery. **UI work (M15.5) is out of scope.** Two other engineers are working in parallel on M14a (live restream) and M16a (agencies). Keep edits to shared files (`config/models.py` `AppConfig`, `pipeline/channel.py`, the generated web client, `docs/PROGRESS.md`) small and additive so rebases stay trivial.

## Required
1. **`dsp/squelch.py` (test-first).**
   - `SquelchConfig` pydantic model, exactly as in PLAN M15.1. Validate `close_dbfs <= open_dbfs` and sensible ranges (dBFS in [-120, 0], attack 0–2000 ms, hang 0–30000 ms, margin 1–40 dB).
   - A pure `Squelch` state machine fed per frame with `(level_dbfs, stream_time_s)`, returning `open: bool` and whether it changed:
     - hysteresis between open and close
     - attack before opening, hang before closing
   - **`noise_floor` mode:** a bounded rolling low-percentile floor estimate (the quietest ~10 % of frames over a window of about 30 s; O(1) or O(log n) per frame, no unbounded growth). It opens at floor + `floor_margin_db` and closes at floor + margin − (open − close) hysteresis. Document the estimator in the module docstring.
   - Coverage ≥95 % (dsp gate).
2. **Config (`config/models.py`).**
   - `SourceBase.squelch: SquelchConfig = SquelchConfig()` (mode off).
   - Rename the RTL-SDR integer to `RtlSdrSource.rtl_fm_squelch: int = 0` and update `sources/rtlsdr.py`. A legacy integer `squelch` on an rtlsdr source must still load: use a before-validator that moves it to `rtl_fm_squelch`, so saving writes the new shape. Test load, save, then reload.
   - Update the existing web source form's field name (`web/src/features/sources/Sources.tsx` posts `squelch` as a number) to `rtl_fm_squelch`. That is the only UI change allowed.
3. **Pipeline (`pipeline/channel.py`).**
   - Keep per-channel squelch state, using the spectrum level the channel already computes (don't add a second FFT).
   - **Never gate detection:** the matcher, discovery, ring buffer and recorder input stay raw. Add a test in which a tone page arrives while squelch is closed and is still detected, with the same detection time as with squelch off.
   - Publish `SquelchChanged(source_id, open, level_dbfs, at)` on the event bus (typed in `events.py`) only on transitions.
   - Expose the current state as a small read-only accessor (for example `channel.squelch_open`), so the parallel M14 live stream can gate on it later. Do not implement streaming.
   - **Recording:** add `RecordingPolicy.stop_on_squelch: bool = False`. When true and squelch mode is not off, post-roll ends at squelch close (after hang) instead of the silence threshold. `max_s` and the existing behaviour stay unchanged when false.
   - **Watchdog:** while squelch is closed, or for an rtlsdr source with `rtl_fm_squelch > 0`, silence is expected and must not raise a flatline fault. No-frames detection stays active.
4. **Outputs.**
   - WS level payload gains `squelch_open` (omitted or null when mode is off; say which).
   - The source status in the API gains `squelch_open` and `last_activity_at` (last open transition, UTC).
   - MQTT HA discovery: a `binary_sensor` per source, "<source name> activity", `device_class: sound`, published only when that source's squelch mode is not off. Retained discovery config is cleared when the mode turns off or the source is deleted, matching how feed-health sensors are handled.
   - Regenerate the web client (`just gen-api`).
5. **Tests.**
   - Unit tests for hysteresis, attack, hang and noise-floor tracking.
   - **Hypothesis property:** a level sequence confined strictly between `close_dbfs` and `open_dbfs` produces zero transitions, and noise near the threshold produces at most one transition per hang window.
   - **Golden:** synthetic voice bursts in noise (use `dsp/generator.py`) give exactly one open/close pair per burst.
   - An integration test through the channel with a file source.
   - The legacy rtlsdr config migration.
   - The MQTT discovery payload and its clearing.
6. **Docs.** Add a "Squelch" section to the public tuning guide (`docs/` page used by mkdocs), stating clearly that squelch does not affect detection. Update the threat model or ASVS docs only if you add attack surface (you shouldn't).

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate: no skips, no lowered coverage, no `# type: ignore`/`noqa` without a same-line justification.
- Never print, read into logs, or commit anything from `backend/tests/fixtures/private/`.
- No legacy product naming (the clean-room pre-commit hook enforces it).
- Never commit or push. Don't bump unrelated pins.

## Definition of done
- `just check` passes. Paste the pytest and vitest summary lines.
- `just ci-local` with `TONEWATCH_E2E_PORT=8803` passes, including api-drift and e2e. If the Windows Playwright launcher hangs only in teardown after every spec passes, say so exactly.
- In `docs/PROGRESS.md`, M15.1–M15.4 are marked `[~] PENDING-REVIEW`, one line each.
- The final report lists every changed file, the squelch estimator's complexity, the exact WS/API/MQTT payload changes, and the test that proves detection is not gated.
