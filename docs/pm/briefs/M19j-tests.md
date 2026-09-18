# Brief: M19j-tests — write the mandatory drill tests A–E, fix what they expose, and reach the gates

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b658-aabe-7ee1-86f4-c77689491ae8`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19j` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8850`. `docs/pm/briefs/M19j-drill.md` still applies in full.

## Status
Your report is honest, but the implementation has only two waveform unit tests. **None of the mandatory tests A–E exist.** The code exists now, so these tests must be **behavioural and adversarial**, aimed at finding bugs in what you wrote. For each test, record whether it passed immediately or failed; for each failure, show the fix with file:line. **Paste results into your progress messages as you go**, in case your turn is cut off.

## Suspected defects the tests must probe (the PM's review; confirm or refute each with a test)
1. **Tones at exactly `min_s`.** `pipeline/drill.py` `build_waveform` synthesizes each tone at exactly `min_s`. The matcher emits when a tone *reaches* `min_s`, and 100 ms framing plus the segmenter's dropout handling can leave a tone of exactly `min_s` measured short. Use a duration safely inside the window, e.g. `min(max_s, min_s + 0.5 * (max_s - min_s))` and at least `min_s + 0.3` when allowed, and prove detection in test A.
2. **Drill marking on the call.** `Channel._apply_drill` marks frames via `_current_frame_drill`, but the call's recording continues past the injected audio (post-roll, silence stop). Prove the call row, `RecordingReady` and **the recording_ready dispatch** carry `drill: true`, even though they are emitted **after** the injected frames end. Prove it with `voice_s=0` too, where only tones are injected.
3. **Mix mode halves live audio for the whole drill.** That's acceptable only if documented. Prove the peak is ≤ 1.0 and that live audio is at full level again after the drill.
4. **A drill across a channel stop or restart.** If the supervisor restarts the channel mid-drill, the leftover drill state must not leak into the new channel instance, and the drill must not stay "active" forever (the per-source 429 would then block drills permanently). Test it.
5. **Admin alerts (M19.2).** A drill whose alert target fails must not count toward the consecutive-failure admin alert. Grep where that counter is updated and prove it with a test.

## Required tests (the full M19j brief A–E)
- **A. End to end** through the real supervisor with a `FileAudioSource` of silence or noise (realtime or fast mode):
  - `POST /api/admin/drill` for a two-tone set gives 202, then exactly **one** call with `drill` true and a recording
  - `ToneDetected` and `RecordingReady` events with `test` and `drill`
  - one dispatch per configured target through the existing fakes (MQTT, HA event, webhook JSON, script argv/env, Meshtastic text with the "DRILL" prefix within its length budget), each carrying the marker
  - a real (non-drill) detection afterwards is **not** marked
- **B. Mix vs replace:**
  - in replace mode, live frames inside the drill window don't reach the DSP
  - in mix mode, both do, with the peak at most 1.0
  - live input resumes afterwards
  - the channel task object is unchanged (no restart)
- **C. Retention:** a drill call older than `drill.retention_hours` is deleted with its recording by the retention job **and** counted in the retention preview as `drills`. `keep: true` survives, and normal calls of the same age follow the normal policy.
- **D. Safety:**
  - no auth gives 401; a cookie without CSRF gives 403
  - ingress gives 403
  - a second drill on the same source while one is active gives 429, and more than 1 per minute globally gives 429
  - an unknown source or tone set gives 404, a disabled one 409, and a stopped source 409
  - it's audited with source, tone set, mode and actor
- **E.** The admin-alert exclusion (item 5), plus item 4.

## Migration
You added `0009_call_drill`. Confirm its `down_revision` is `0008_recording_created_at`, and that `upgrade_database` from 0008 to 0009 works on a DB populated with calls (existing calls get `drill` = false). Parallel engineer M19i must **not** add a migration; the PM coordinates.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter or item, marking "passed immediately" or showing its failing line, the fix (file:line) and its passing line.
- `just check` green, with **every** `check_package_coverage.py` line at least 1 % above its gate. Paste the lines for `pipeline` (95 %), `dsp` (95 %), `recording`, `alerts` and `api/routes/admin.py`.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19j. **Parallel engineer M19i** is in `storage/db.py`, the backup code and the CLI. Don't touch those.
