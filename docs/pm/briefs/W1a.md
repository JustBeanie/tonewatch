# W1a brief: composition-root wiring (the running app must record, watch, retain and alert)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, **high**

## Why this exists
M3, M4 and M7 each built well-tested units. PM review of the M6b e2e work found they are **never assembled in the running app**. A real `tonewatch serve` detects tones and opens calls, but it **never writes a recording**. The e2e harness hid this by faking a recording URL.

Your job is to wire the composition root and prove it with tests that go through the **real app lifespan** (`create_app` → `Supervisor` → `Channel`). Injected `channel_factory` fakes and hand-built `Channel(recorder_hook=...)` don't count as evidence.

Read these before starting:
- `AGENTS.md`, `PLAN.md` (Architecture, M3, M4, M7), `docs/PROGRESS.md`
- `backend/src/tonewatch/{api/app.py,pipeline/supervisor.py,pipeline/channel.py,pipeline/watchdog.py,pipeline/persistence.py,recording/*.py,alerts/dispatcher.py,settings.py}`
- `backend/tests/golden/test_recording.py`, which shows the recorder working when hand-wired.

## PM-verified findings (fix all of them)
1. **No recorder in production.**
   - `pipeline/supervisor.py` `_run_source` calls `self.channel_factory(source, self.config.tone_sets, self.bus, self.clock)` with no `recorder_hook`.
   - `CallRecorder` is referenced in `src` only by `recording/__init__.py`, and `RecordingReady` is never published by the app.
   - **Wire it:** build one recorder per channel from settings. Use the recordings dir from settings; add-on mode writes under `/media/tonewatch` per PLAN M4.3, so check `settings.py` and add a setting only if missing.
   - Sequential calls on one channel must each produce their own recording. Decide whether that means a recorder per call or a resettable one, and prove it.
2. **The watchdog isn't connected.**
   - `_run_source` creates a `Watchdog` and runs its task but never passes `watchdog=` to the channel, so `Watchdog.on_frame` is never called.
   - Prove, with a test, what the current behaviour is on a healthy feed (expected: `no_data` goes unhealthy after `no_data_s`), then fix it.
3. **Retention never runs.** `api/app.py` lifespan builds `Supervisor(app.state.config, bus, sessions)` without `retention_service`. Build it from the config/settings retention policy.
4. **No finalize on source end.**
   - When the source iterator ends (file EOF with `loop: false`, a stream drop, `rtl_fm` exit) or the recorder's `should_stop` breaks the loop, `Channel.run` calls `_close_call()` but never finalizes the in-progress recording (`CallRecorder.finish()`), so that audio is lost.
   - Finalize on normal end **and** on the error path.
   - On cancellation (shutdown or reload), finalize within the supervisor's bounded shutdown timeout, or document and test why that's skipped.
5. **The hook-signature shim swallows errors.** `channel.py` calls `recorder_hook(frame, ringbuffer, output, call, "active")` and on `TypeError` retries `recorder_hook(frame, ringbuffer)`. A genuine `TypeError` raised *inside* the hook is silently re-dispatched. Replace the shim with one typed `Protocol`, update the tests that relied on the 2-arg form, and make hook errors propagate to the supervisor's restart/backoff path.
6. **Alerts must fire from the real app.** M7 wired `AlertDispatcher` in `supervisor.py`. Confirm a real call with a recording produces `recording_ready` alert attempts carrying a recording URL that the API actually serves.

## Required tests (exact names; each must fail on today's `main`)
Write the test first and confirm it fails. Report the failing output (one line each) in your final message.

In `backend/tests/integration/test_app_wiring.py`, everything goes through `create_app(...)` with its lifespan, a temp data dir, a **file** source built from `tonewatch.dsp.generator` audio, and fast (non-realtime) mode unless stated:
- `test_app_records_call_end_to_end`
  - A two-tone page followed by about 3 s of voice-like audio produces a `Call` row with a `Recording` row.
  - The file exists under the recordings dir and decodes with PyAV to a duration within ±0.5 s of the expected trimmed length.
  - `GET /api/recordings/{id}` (authenticated) returns 200 with `audio/*`, and a `Range: bytes=0-99` request returns 206.
- `test_source_eof_during_post_roll_finalizes_recording`: `loop: false`, with the audio ending about 1 s after the final tone (well inside `post_s`). A recording is still written and persisted.
- `test_sequential_calls_on_one_channel_produce_two_recordings`: two pages separated by more than the merge window give two calls and two distinct recording files.
- `test_healthy_feed_stays_healthy_through_supervisor`: a real channel with frames flowing for longer than `no_data_s` (injected clock/sleep) publishes no `FeedHealthChanged(healthy=False)`. A second phase that stops the frames **does** go unhealthy with `no_data`.
- `test_retention_runs_in_app_lifespan`: pre-seed recordings older than the configured max age, start the app, and assert they are pruned (injected sleep or clock, with no real 24 h wait).
- `test_webhook_alert_fires_for_real_recorded_call`:
  - A local HTTP receiver (in-test server on `127.0.0.1`, ephemeral port) gets `pre_alert` and `recording_ready`.
  - The `recording_ready` payload's recording URL, fetched through the app, returns 200 audio.
  - `AlertAttempt` rows are persisted with the correct `phase`.
  - Note: loopback webhook targets may be refused by `alerts/urlsafety.py`. If so, use the documented test override. **Don't weaken the production default.** State which override you used and cite the line.

In `backend/tests/unit/test_pipeline.py`:
- `test_recorder_hook_type_error_propagates`
- `test_channel_finalizes_recording_on_source_error`

## Constraints
- **No `pragma: no cover`, no new `# type: ignore` / `noqa` without a same-line reason, and no lowering of coverage gates.** `pipeline` stays ≥95 and `recording` ≥90.
- Don't change DSP behaviour or golden expectations. If a golden test changes, stop and explain why in the report.
- Keep `Supervisor`'s injectable seams (`channel_factory`, clock, sleep) for unit tests, but the defaults must be the fully wired production objects.
- Stay in `backend/` and `docs/`. No web changes, since W1b does the SPA and e2e.
- Update `docs/security/threat-model` entries only if the wiring changes a documented data flow (recordings dir, retention). Keep S3's integrity tests passing.

## Definition of done
- All 8 named tests exist, each with its pre-fix failure line quoted in the report.
- `just check` exits 0; run it **last** and paste the unfiltered tail.
- `pre-commit run --all-files`, `just api-drift` and `just security` exit 0.
- `grep -rn "pragma: no cover" backend/src` is empty.
- `docs/PROGRESS.md` gets a new `## W1: Wiring` section with `W1a.1`–`W1a.6`, one per finding, each citing its test.
- The final message has a **finding → fix (file:function) → test** table.
