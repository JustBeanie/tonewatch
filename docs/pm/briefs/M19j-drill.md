# Brief: M19j — M19.4 end-to-end drill (backend + API)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19j` (branch `m19j`). **E2E port:** `TONEWATCH_E2E_PORT=8850`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19 intro and **M19.4** (~line 670).
- `dsp/generator.py` (`tone`, `silence`, `voice_like`, `concat`).
- `pipeline/channel.py` and `pipeline/supervisor.py`: how frames flow from a source into the DSP, the ring buffer and the recorder, and where you can inject frames into a **running** channel without restarting it.
- `events.py`: the `test` flag that already exists on detection events, and how `alerts/dispatcher.py` propagates `test` into payloads (lines ~78, 346–365, 536, 626–633).
- `alerts/ha_discovery.py` and `alerts/mqtt.py`: how `test` shows up in MQTT/HA events. The existing `POST /api/tonesets/{id}/test` simulates a detection **without** audio; the drill differs by pushing real audio through the whole chain.
- `recording/retention.py`, for auto-deleting drill calls.

## Required
1. **Injection.** `POST /api/admin/drill` with body `{source_id, toneset_id, mode: "mix"|"replace", voice_s: 0..20 (default 5), keep: bool = false}`.
   - Synthesize the tone set's sequence with `dsp/generator.py`, using each tone's nominal frequency and a duration inside `[min_s, max_s]`.
   - Optionally follow it with `voice_like` for `voice_s` seconds, then feed it into the running channel's input at real-time pace, **mixed** with live input (with a safe gain and no clipping) or **replacing** it for the drill's duration.
   - The channel must not restart, and live input resumes afterwards.
   - It returns `{drill_id, expected_duration_s}` right away (202). Progress arrives as events.
2. **Marking.**
   - The resulting call and every downstream artifact carry `drill: true` **and** `test: true`: the DB call row (add a column via a migration **0009** if needed, and say so), `ToneDetected`/`RecordingReady` events, MQTT and HA event payloads, webhook and script payloads, and the Meshtastic text (a "DRILL" prefix within its length budget).
   - Grep every alert target type and prove each one carries the marker.
   - Admin alerts (M19.2) must not fire because of a drill.
3. **Auto-delete.** A drill call and its recording are deleted after `drill.retention_hours` (a new setting, default 24) unless `keep` is true. This runs in the existing retention job and is included in the retention preview counts (as `drills`).
4. **Safety.**
   - Admins only (`write_auth`), refused through ingress. Document why: it triggers real pages marked as drills.
   - Audited, with source, tone set, mode and who ran it.
   - Rate-limited: at most 1 active drill per source, and at most 1 per minute globally; otherwise 429.
   - Unknown or disabled source or tone set gives 404/409.
   - A source that isn't running gives 409.
   - Injection stops cleanly if the channel stops mid-drill.

## Mandatory tests (write first; show each failing line)
- **A. End to end** through the real supervisor and a `FileAudioSource` running in realtime or fast mode:
  - a drill of a two-tone set produces exactly one call with `drill` true
  - a recording
  - `ToneDetected` and `RecordingReady` events with `test` and `drill`
  - one dispatch per configured target, captured by fakes, whose payloads carry the marker (MQTT, HA event, webhook JSON, script argv/env, Meshtastic text)
- **B. Mix vs replace:**
  - in replace mode, live input frames during the drill window don't reach the DSP
  - in mix mode, both do; the output peak stays ≤ 1.0
  - live input resumes after the drill (assert on frames after it)
  - the channel task identity doesn't change (no restart)
- **C. Retention:**
  - a drill call older than the window is deleted by the retention job and counted in the preview
  - `keep: true` survives
  - normal calls are unaffected
- **D. Safety:**
  - no auth gives 401; a cookie without CSRF gives 403
  - ingress gives 403
  - a second drill on the same source gives 429
  - unknown source or tone set gives 404
  - a stopped source gives 409
  - it is audited
- **E. Admin alerts don't fire on drill-originated conditions:** a drill whose alert target fails doesn't count toward the consecutive-failure admin alert.
- **F.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` fully green, with every `check_package_coverage.py` line (especially `pipeline` and `dsp`, whose gates are 95 %) at least 1 % above its gate. Then `just ci-local` up to `api-drift` (run `just gen-api`). `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark M19.4 `[~] ... — PENDING-REVIEW`.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate. No real incident data. **No real sockets or brokers** (use the existing fakes).
- Add a threat-model row with id **TM-051** (M19i takes TM-050) and a `docs/guide/admin.md` section.
- **Parallel engineer M19i** works in `storage/db.py`, the backup code and the CLI `backup` subcommand. **If you need migration 0009, tell the PM in your report**, because M19i must not add one. Keep any `api/app.py` edit to one router registration.
