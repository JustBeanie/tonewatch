# PM follow-up: W1a-fix shutdown finalize is not reliable under a slow host (real product race)

**Resuming the W1a thread.** You are in the `tonewatch-hotfix` worktree (branch `hotfix-webhook-race`, based on `main` at `7c79696`). W1b is running in the main checkout, so stay here.

## Evidence
`test_app_shutdown_during_post_roll_finalizes_recording_within_timeout` has been green 5 of 6 times on CI (and 15/15 on the PM host), but on ubuntu-latest in CI run 34666653411 it failed `assert 0 == 1` (no `Recording` row). The captured log shows:
```
{"event": "Exception during reset or similar", "exc_info": ["<class 'asyncio.exceptions.CancelledError'>", ...], "timestamp": "…49.501705Z"}
```
That is about 1.2 s after start, right when `shutdown_timeout_s=1` expired. On a slower host the shutdown budget cancels in-flight work: the encoder and/or the persistence session commit. So the recording row is lost, while the MP3 may already be on disk.

**Why it matters:**
- **Orphaned files:** a file with no DB row is invisible to the API and to retention, so it is never pruned.
- **Slow targets:** a Raspberry Pi is much slower than a CI runner.
- **Power loss** leaves the same orphans.

## Required
1. **Deterministic reproduction first; no reliance on host speed.**
   - Add injectable delays (test seams on the encoder and/or the persistence session, like `_delayed_session_factory` already used in `test_app_wiring.py`) so the race reproduces on every run on any host.
   - Quote the failing output on the current tree in your report.
2. **Shutdown ordering fix.**
   - `Supervisor.stop` must give channel finalization (encode) its own bounded budget.
   - Then persistence must **drain** the resulting `RecordingReady`/`CallClosed` events with a separate bound.
   - An in-flight DB commit must never be cancelled mid-transaction: shield it, or let it finish within the drain budget.
   - If a budget truly expires, the state must stay **consistent**. Pick one and document it in ADR `docs/decisions/0006-shutdown-finalize.md`:
     - **(a)** the call is closed with status `interrupted` and the partial file is removed, **or**
     - **(b)** the file is kept and gets a row on next start (see 3).
   - Keep total shutdown bounded, and document the worst case: finalize budget + drain budget.
3. **Startup reconciliation of orphans.**
   - On app start, before channels run, scan the recordings root for audio files that have no `Recording` row.
   - Either insert rows (duration and size read off the event loop, `call_id` parsed from the file name, with the call marked `interrupted` if it isn't closed) **or** delete them, consistent with the ADR.
   - Never touch files outside the recordings root. Reuse the retention escape checks.
4. **Tests** (each must fail on the current tree first; quote one failure line each):
   - `test_shutdown_slow_encoder_still_leaves_consistent_recording_state`: the encoder is delayed close to the finalize budget, and the outcome matches the ADR on every run.
   - `test_shutdown_never_cancels_inflight_persistence_commit`: a commit delayed to 0.5 s during `stop()` ends with the row committed.
   - `test_startup_reconciles_orphan_recording_files`: a pre-seeded orphan MP3 under the recordings root is reconciled, and a file outside the root is untouched.
   - Make `test_app_shutdown_during_post_roll_finalizes_recording_within_timeout` deterministic (seams, not wall-clock luck), or replace it with the tests above and say so.

## Also apply the local-vs-CI rules (see `docs/pm/carryover.md`)
- Run `rg -n "skipif\(\s*sys.platform"` and update any Linux-only test touching changed code.
- Integration tests wait for **persisted** state with a bounded helper (for example `_wait_for_attempt_phases`), never for a proxy event.

## Constraints
- Stay in `backend/` and `docs/`.
- No `pragma: no cover`, no `mark.skip`, no lowered gates (`pipeline` ≥95, `recording` ≥90).
- Don't change DSP or golden expectations.

## Definition of done
- For each new test, run it 10 times in a row, and show the loop and its pass count.
- `pre-commit run --all-files`, `just api-drift` and `just security` exit 0. Then run `just check` **last** and paste its unfiltered tail.
- The final message has a **finding → fix (file:function) → test** table and the ADR choice.
