# Brief: M15a-fix2 — finish squelch tests and wiring (resume thread 01a09968)

**From:** PM (Claude) · **To:** the same Codex engineer (resumed, thread `01a09968-2163-7eb3-b3e5-8a30671139fa`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m15a`. **E2E port:** `TONEWATCH_E2E_PORT=8803`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## PM verification of your last run
Thank you for reporting honestly what was incomplete. Verified in code:
- ✅ Watchdog: separate software/RTL inputs; the channel passes `None` when mode is off (`channel.py:288-290`); `test_watchdog_squelch_inputs_keep_off_and_rtl_silence_distinct`.
- ✅ Legacy migration keeps a dict, migrates ints, rejects bool, rejects non-rtlsdr ints (tests present).
- ✅ Supervisor-less source status returns `null`.
- ✅ `rms_dbfs` has RMS semantics again.

**Still open:**
- **`squelch_level_dbfs` is declared but never set.** It exists only in `events.py:71`; the channel never fills it, so the WS always sends `null`.
- **Most of the required test matrix is missing.**

**Your e2e failure was the environment, not the app.** In cmd, `set TONEWATCH_E2E_URL= && just e2e` sets the variable to a single space. `playwright.config` treats any non-empty `TONEWATCH_E2E_URL` as the base URL, hence `Cannot navigate to invalid URL`. Don't set `TONEWATCH_E2E_URL` at all. Use `set TONEWATCH_E2E_PORT=8803&& just e2e` (no space before `&&`), or on PowerShell `$env:TONEWATCH_E2E_PORT='8803'; Remove-Item Env:TONEWATCH_E2E_URL -ErrorAction SilentlyContinue; just e2e`.

## Required (each item needs a new test; paste its name and passing line; red-first where it covers a fix)
1. **Wire `squelch_level_dbfs`.** When squelch mode is not off, `ChannelLevel.squelch_level_dbfs` carries the level the squelch compared against (the spectrum level used by `Squelch.feed`, not RMS); it is `null` when off. Test through `Channel` with a file/fake source at a known level. Regenerate the WS/API types if they include it.
2. **Detection is not gated.** A tone page arrives while squelch is **closed** (level mode with `open_dbfs` above the page level, or during attack). The `ToneDetected` event is still published, with the **same `detected_at`** as the identical run with mode off. Run it through `Channel`.
3. **The flatline regression, end to end.** Through `Channel` plus a real `Watchdog` with an injected clock: a squelch-off source feeding digital silence raises the flatline fault after `flatline_s`; the same source in level mode (closed) does not; an rtlsdr source with `rtl_fm_squelch > 0` does not.
4. **Hypothesis properties on `Squelch`:**
   - (a) levels strictly between `close_dbfs` and `open_dbfs` never transition
   - (b) random levels give at most one transition per hang window after the first open
   - (c) in `noise_floor` mode, the open threshold is never below floor + `floor_margin_db`
5. **Golden bursts.** Voice-like bursts in noise from `dsp/generator.py` give exactly one open/close pair per burst, with times within one frame hop (plus attack or hang) of the burst edges.
6. **`stop_on_squelch`:**
   - with it true, post-roll ends at squelch close + hang, and the recording finishes and is persisted
   - with it false, the silence-threshold behaviour is unchanged
   - in a stacked call where only one tone set has the flag, the normal stop applies (document which rule you implement and test it)
7. **`SquelchChanged` fires only on transitions.** N frames with a constant open state publish exactly one event.
8. **MQTT/HA discovery:**
   - the activity `binary_sensor` config is published only when mode is not off
   - `ON`/`OFF` goes out on `SquelchChanged`
   - the retained config is cleared (empty retained payload) when the mode changes to off via reload, and when the source is deleted
9. **Source status API.** List and detail with no supervisor give `null`/`null`. With a running channel after an open transition, `squelch_open` is true and `last_activity_at` is ISO UTC.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification.
- Never `git add`, commit or push.
- Don't describe work you haven't done. If time runs out, report precisely what remains, as you did last time.

## Definition of done
- `just check` passes. Paste the pytest count (it was 412) and the new count, vitest, and the dsp and pipeline coverage.
- `just e2e` with `TONEWATCH_E2E_PORT=8803` and `TONEWATCH_E2E_URL` unset: 4 specs pass. If the Windows launcher hangs only in teardown after all pass, say so.
- `just ci-local` passes up to api-drift. If api-drift fails only on uncommitted generated files, paste `git diff --stat -- web/src/api`.
- A table maps each numbered requirement to its test name(s).
