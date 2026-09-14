# Brief: M15b — auto squelch, calibrate endpoint, squelch diagnostics (PLAN M15.6 + M15.7)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m15b` (branch `m15b`, based on main `f643f97`, which includes M14a live restream and M15a squelch). **E2E port:** `TONEWATCH_E2E_PORT=8807` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.
**Git:** your sandbox can't write git state in this worktree. Never run fetch, stash, merge, add or commit. Read-only `git diff`/`status`/`show` is fine.

## Read first
- `PLAN.md` M15.6 and M15.7, which are the spec.
- `backend/src/tonewatch/dsp/squelch.py` (`SquelchConfig`, `Squelch`, the 0.5 dB histogram over [-120, 0]).
- The squelch wiring in `pipeline/channel.py` (`_update_watchdog_squelch`, `_feed_live(gate_open=...)`, `SquelchChanged`).
- The source status in `api/routes/config.py`, and the WS level messages.

## Required
1. **`mode: "auto"`** on `SquelchConfig`. New fields, all validated, with bounds; keep `extra="forbid"`:
   - `auto_window_s` (default 300; 30–1800)
   - `auto_min_samples_s` (default 30; 5–300; must be ≤ `auto_window_s`)
   - `auto_k` (default 1.5; 0.25–4)
   - `min_margin_db` (default 6; 1–40)
   - `max_margin_db` (default 25; 1–60; ≥ `min_margin_db`)
   - `stuck_open_s` (default 600; 30–7200)
   - `max_transitions_per_min` (default 20; 2–600)

   Existing configs without these keys must load unchanged; test a pre-M15b YAML fixture.
2. **Estimator** (pure, in `dsp/squelch.py`, reusing the bounded histogram and eviction):
   - `floor` = p10 and `spread` = p50 − p10 over `auto_window_s`.
   - `open` = floor + clamp(`auto_k`·spread, `min_margin_db`, `max_margin_db`) + the stuck-open step (item 4).
   - `close` = open − max(3, spread/2).
   - Expose p10/p50/p90 through a small public method, so the calibrate endpoint uses the **same** code.
   - **Refactor the O(241) percentile scan into one helper shared by `noise_floor` and `auto`.** `noise_floor` mode behavior must be byte-for-byte unchanged; the existing tests must pass untouched.
3. **Calibrating fail-open:** until `auto_min_samples_s` of stream time has been observed, `calibrating = True` and the squelch reports **open** (`gate_open=True` for live, `squelch_open=True` for display). The first transition out of calibrating emits one `SquelchChanged` if the state changes.
4. **Health flags,** in stream time and never wall clock:
   - **`stuck_open`:** open continuously longer than `stuck_open_s` sets the flag and adds a +3 dB margin step. Allow at most +12 dB total; the steps decay back one per `stuck_open_s` of normal operation. The flag clears once the squelch has closed and stayed closed for `hang_ms` + 5 s.
   - **`chatter`:** more than `max_transitions_per_min` in a trailing 60 s window sets the flag and doubles the effective hang, capped at 4× configured `hang_ms` and 30 s. The flag clears after 60 s under the limit, and the hang returns to the configured value.
   - A flag change emits a new domain event `SquelchHealthChanged(source_id, stuck_open, chatter, at)`, transition-only, and is logged with structlog at warning (on set) and info (on clear). Never silent.
5. **Detection stays ungated in every mode.** Extend the existing through-`Channel` test (`test_channel_live_gate_follows_squelch_without_gating_detection` pattern) with `mode="auto"`, covering calibrating (gate `True`) and then real transitions, with `ToneDetected` times identical to mode `off`.
6. **Diagnostics.** Source status (list and detail) and the WS level message gain:
   - `squelch_mode_effective`, `noise_floor_dbfs`, `open_dbfs_effective`, `close_dbfs_effective`
   - `calibrating`, `stuck_open`, `chatter`, `transitions_per_min`

   All are `null` when the supervisor or channel is absent, following the M15a null guard pattern. Keep existing keys unchanged, and keep `live_listeners`.
7. **Calibrate endpoint:** `POST /api/sources/{id}/squelch/calibrate`, body `{seconds: 5..120}`.
   - `write_auth` + CSRF + audit event `squelch_calibrated` (source id, seconds, suggested thresholds).
   - It samples the **running channel's** level stream for N seconds; don't open a second source or device. Use a subscriber/tap on the channel, bounded and removed in `finally`, including on client disconnect or cancel.
   - Returns `{floor_dbfs, spread_db, p10, p50, p90, histogram: [{dbfs, count}] (coarse, 3 dB buckets), suggested: {mode: "level", open_dbfs, close_dbfs}}`.
   - Errors: 404 unknown source; 409 source not running; 422 bad seconds; 429 when a calibration is already running for that source (one at a time).
   - Hold no config write; applying the suggestion is a separate normal source update.
8. **Web client:** run `just gen-api`. No UI work in this brief; M15.5 comes later. If generated types change, still compile `Sources.tsx`, with minimal type fixes only.
9. **Docs:** the squelch guide section on auto mode, the flags, and calibrate; a PROGRESS note on M15.6/M15.7 marked PENDING-REVIEW. Update the threat model and ASVS entries for the new endpoint, following the existing conventions: quote-all CSV, LF, line anchors re-derived.

## Mandatory tests
Each must exist; the report maps test name to letter.
- **A. Hypothesis:** auto `open` is monotonic non-decreasing in the floor (same spread), and `open − floor` always lies within [`min_margin_db`, `max_margin_db` + stuck step].
- **B. Hypothesis:** `close ≤ open − 3` always.
- **C. Golden busy channel:** synthetic levels with noise at a true floor (e.g. −70 dBFS ± 1.5) and voice-like bursts (−35 ± 5) covering **60 %** of a 5 min window. The estimated floor is within 3 dB of the true floor.
- **D. Calibrating:** before `auto_min_samples_s`, open = True and calibrating = True; after, calibrating = False and the state follows thresholds.
- **E. Stuck carrier:** a constant high level longer than `stuck_open_s` raises `stuck_open` and the margin steps by +3, capped at +12 across repeats. Removing the carrier clears the flag after the hang window. Assert the `SquelchHealthChanged` sequence (set, then clear) exactly.
- **F. Chatter:** alternating levels above/below the thresholds faster than the limit raise `chatter` with the effective hang doubled (and capped). Calm input for 60 s clears it and restores the hang. Assert the event sequence.
- **G. `noise_floor` regression:** the existing `test_squelch.py` tests pass unmodified. Add one test that the shared percentile helper gives the same floor as before for a fixed sequence.
- **H. Config:** a pre-M15b YAML loads; invalid bounds (`auto_min_samples_s` > `auto_window_s`, `max_margin_db` < `min_margin_db`) give 422 through the source API naming the field.
- **I. Channel:** auto mode, calibrating → transitions, gate values recorded, detection times identical to mode off.
- **J. Diagnostics:** the list and detail status include all 8 fields with the right values for a running fake channel, and `null` without a supervisor. The WS level message includes them.
- **K. Calibrate API** (httpx ASGI + fake running channel emitting known levels):
  - 200 with the exact suggestion
  - identical twice in a row (±1 dB, the PLAN "stable" rule)
  - 401 without auth; 403 without CSRF
  - 404, 409, 422 (4 and 121 seconds), and 429 for concurrent calls
  - the audit row written
  - the tap removed after success **and** after a cancelled request (assert the channel's tap count returns to 0)
- **L. Security regression:** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Evidence (the report is rejected without this)
- A table: test name → letter (A–L).
- For each required item 1–7, the red-first line of its test (run before the implementation), the passing line, and a diff excerpt with file:line.
- The pytest count before (baseline on this worktree: run `just test` first and record it) and after.
- `just check`, `just e2e` (port 8807) and `just ci-local` up to api-drift, with `git diff --stat -- web/src/api`.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification. Coverage gates stay (dsp and pipeline ≥ 95 %).
- No new dependencies. No real radio data; synthetic levels only.
- Never write git state. Don't describe work you haven't done.
