# Brief: M15a-fix — squelch review failures (resumed thread)

**From:** PM (Claude) · **To:** the same Codex engineer · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m15a`. **E2E port:** `TONEWATCH_E2E_PORT=8803`.
If `uv` complains about the Python minor-version link, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## Verdict: FAIL (spec + bugs)
The squelch state machine itself is good: bounded, clear, O(1) histogram. But the brief's required tests are almost entirely missing (only 4 unit tests), and that let a critical regression through. Every fix below needs a **red-first test**: write the test, show it failing against your current code (paste the failure line), then fix.

## Bugs to fix
1. **CRITICAL: flatline detection is disabled for every source with squelch off, which is the default.**
   - In `pipeline/channel.py` the frame loop calls `self.watchdog.set_squelch_open(state)` on every spectrum frame.
   - In `off` mode, `Squelch.feed` returns `(False, False)`, so `set_squelch_open(False)` sets `squelch_expected = True`, and a dead feed never raises a flatline fault.
   - It also overwrites the `rtl_fm_squelch > 0` flag that `_observe_frame` set.
   - **Fix:** the watchdog expects silence **only** when (software squelch mode is not off **and** squelch is closed) **or** `rtl_fm_squelch > 0`. Keep these as two separate inputs combined in the watchdog, not one flag both places overwrite. Pass `None` when mode is off.
   - **Tests:**
     - (a) squelch off plus a flatline feed still raises the flatline fault after `flatline_s`, through a real `Channel` with a file/fake source
     - (b) level mode with squelch closed on silence raises no flatline fault
     - (c) `rtl_fm_squelch > 0` raises no flatline fault even when software squelch opens and closes
     - (d) no-frames/disconnect detection still fires in all three cases
2. **The legacy migration drops new-style config.** `RtlSdrSource.migrate_legacy_squelch` pops `squelch` whenever `rtl_fm_squelch` is absent, even when `squelch` is a dict (a `SquelchConfig`). A hand-written `squelch: {mode: level, …}` on an rtlsdr source is silently lost.
   - **Fix:** migrate only when `squelch` is an `int` (not `bool`); otherwise leave it in place.
   - **Tests:** a legacy int migrates; load → `store.save` → reload writes `rtl_fm_squelch` and no int `squelch`; a dict `squelch` on rtlsdr is preserved; a non-rtlsdr source with an int `squelch` is rejected with a clear validation error.
3. **The source status API crashes without a supervisor.** `api/routes/config.py` calls `request.app.state.supervisor.source_status(...)` unguarded. `create_app` accepts `supervisor=None`, so this raises a 500.
   - **Fix:** return `null` for both fields when there's no supervisor or no running channel.
   - **Tests:** list and detail with no supervisor, and with a running channel after an open transition (`squelch_open` true, and `last_activity_at` as ISO UTC).
4. **Unrequested level-meter semantics change.** `_publish_level` now puts the last spectrum `level_dbfs` into `ChannelLevel.rms_dbfs`, so the field name no longer matches its meaning, and the existing meter changed behaviour without a brief or test.
   - **Fix:** keep `rms_dbfs` as RMS exactly as before.
   - **Add** an optional `squelch_level_dbfs: float | None` to `ChannelLevel` and the WS payload, carrying the level the squelch compares against. The M15.5 UI will draw the threshold lines on that value, and it is `null` when mode is off.
   - Regenerate the client.
   - **Test** that `rms_dbfs` is unchanged against a known sine, and that `squelch_level_dbfs` is present only when squelch is enabled.

## Required tests still missing from M15a (from the original brief; all mandatory)
- **Detection is not gated:** a tone page arrives while squelch is **closed**, for example level mode with `open_dbfs` above the tone level or during attack. The detection is still published, with the **same detection stream time** as the identical run with squelch off. Run it through `Channel`, not the engine alone.
- **Hypothesis properties:**
  - a level sequence strictly between `close_dbfs` and `open_dbfs` gives zero transitions
  - random noise near the threshold gives at most one transition per hang window
  - `noise_floor` mode never has an open threshold below floor + margin
- **Golden:** synthetic voice bursts in noise from `dsp/generator.py` give exactly one open/close pair per burst, with times within one frame hop of the burst edges.
- **`stop_on_squelch`:** with it true and squelch enabled, post-roll ends at squelch close + hang, and the recording finishes and is persisted normally. With it false, behaviour is unchanged (silence threshold). Tone sets without the flag in a stacked call keep the normal stop.
- **MQTT/HA discovery:**
  - the activity `binary_sensor` payload is published only when mode is not off
  - an `ON`/`OFF` state is published on `SquelchChanged`
  - the retained discovery topic is cleared (empty retained payload) when the mode changes to off and when the source is deleted
- **`SquelchChanged`** is published only on transitions, never per frame.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification.
- Never print or commit private fixtures.
- Never commit or push.

## Definition of done
- For every numbered bug, the report shows the red-first failure line and then the pass.
- `just check` passes. Paste the pytest and vitest summary lines plus the dsp and pipeline coverage.
- `just ci-local` with port 8803 passes through api-drift and e2e. If api-drift fails *only* because generated files are uncommitted in the worktree, show the exact diff command and output, so the PM can confirm the generated files match a fresh `just gen-api`. If the Windows web-lint or Playwright teardown hangs after all checks pass, say exactly where.
- The report lists every changed file and each new test name mapped to the requirement it covers.
