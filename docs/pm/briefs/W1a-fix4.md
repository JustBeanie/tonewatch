# W1a-fix4: the tone-set hot-reload test hangs the event loop under CPU load

**Resuming the W1a thread (luna high).** The PM will name the worktree at dispatch. It is based on `main` after W1a-fix2/3, S4 and W1b have landed.

## Evidence (PM, 2026-09-11)
- `backend/tests/integration/test_app_wiring.py::test_toneset_created_via_api_detects_on_running_channel` passes alone (3/3, about 2.2 s) and in its file without load.
- Two concurrent `just check` runs on the PM host (S4 worktree and hotfix worktree) both stalled at this test. After 16 min and 10 min their pytest workers had burned about 1000 and about 575 **CPU-seconds** respectively, spinning, not waiting.
- The same stall explains W1b's "backend suite slow in later integration wiring" and terra's sandbox `just check` "stops mid-pytest".
- **Reproduction:**
  1. Start 3 busy-loop Python processes.
  2. Run the test 5 times with `timeout 120` and `-o faulthandler_timeout=30`.
  3. Runs 1–2 passed in 4.8 s. **Run 3 hung for the full 120 s.**
- **It also hangs with NO competing load.** The PM's S4 landing `just check` (tree = `main` `e352849` + S4) ran with no other test suites and still stalled at this test (`test_app_wiring.py .......`) until a 900 s cap killed it. CPU burners make it more likely, but they aren't required. This blocks local `just check` for everyone, so it is top priority.
- **It hangs on GitHub CI too.** On CI run 34672014026 (commit `e352849`), `test-python` on ubuntu-latest and windows-latest ran about 30 min until the PM cancelled them. The Windows log stops at `test_app_wiring.py::test_toneset_created_via_api_detects_on_running_channel`, and ubuntu's last PASSED is the test just before it. ubuntu-arm passed in 2 min. The PM has since added `timeout-minutes` to every CI job, and **quarantined the test with a dated `@pytest.mark.skip`** so CI stays usable.
- **Required deliverable:** remove that quarantine skip, and show the test passing 20/20 under the CPU-burner recipe **and** green on all three CI OSes.
- faulthandler main-thread sample at 30 s:
  ```
  File "backend/src/tonewatch/pipeline/ringbuffer.py", line 106 in snapshot
  File "backend/src/tonewatch/recording/recorder.py", line ??? in <genexpr>
  ```
  Other threads: aiosqlite workers idle, and one `call_soon_threadsafe` from a `to_thread` completion.
- **Why no timeout fires:** `asyncio.wait_for(..., 10)` never raises, so for tens of seconds at a time the loop isn't reaching its timer check, or the test gets stuck again after the timeout, in lifespan teardown.

## Hypotheses to confirm or kill (don't guess; instrument)
1. **Capture re-initialises every frame.** `CallRecorder.process` takes `ring.snapshot_with_time()`, a full 10 s ring-buffer fancy-index copy, when a call starts. If `self.call` keeps being reset (for example after a tone-set-change channel restart, or a call-id mismatch), every frame pays O(ring) and the looping realtime fake-clock source outruns real time.
2. **Fake clock runaway.** The test's `source_sleep` advances fake time without real sleeping, so under load the channel processes unbounded audio per real second and starves the loop.
3. **Teardown livelock.** After a timeout, `Supervisor.stop` → channel cancel → `CallRecorder.finish` (shielded encode, and `except CancelledError: files = await encode_task` doesn't re-raise) → the channel keeps looping.

## Required
1. **A deterministic reproduction that doesn't need external CPU burners.** Use an injected slow `RingBuffer.snapshot`, or a per-frame CPU cost seam, so the hang (or the timeout that should replace it) reproduces on every run on any host. Quote the failure.
2. **Root-cause fix in product code if any hypothesis is a product defect.**
   - **Hot path:** per-frame recorder work must be O(frame), not O(ring buffer), except once at call start. A tone-set channel restart must not produce repeated capture restarts.
   - **Cancellation:** `Channel.run` and `CallRecorder.finish` must honour cancellation. Finishing a shielded encode is fine, but the cancel must propagate afterwards; the task must end.
   - **Yielding:** the channel loop must yield often enough that timers fire even when the source outruns real time.
   - **If the defect is only in the test's fake clock,** fix the test and say so explicitly. Show why production can't hit it: a realtime source sleeps for real.
3. **Hang protection for the whole suite.**
   - Add `pytest-timeout` (dev dependency) with a global per-test timeout, for example `timeout = 120`, and `faulthandler_timeout = 60` in `backend/pyproject.toml`.
   - Hangs must fail as a **named** test with a stack, locally and on CI.
   - Confirm `-W error` still passes.
4. **Tests:**
   - `test_channel_loop_yields_under_runaway_source`: a source that produces frames instantly and endlessly. A concurrent `asyncio.wait_for(..., 0.5)` elsewhere in the loop still fires.
   - `test_recorder_per_frame_cost_is_constant_after_call_start`: count `snapshot` calls, which should be at most 1 per call start, across N frames and a tone-set restart.
   - `test_channel_cancel_ends_task_during_finish`: cancel during a slow encode. The task finishes (row or ADR-0006 reconciliation), and it doesn't keep consuming frames.
   - Run the hot-reload test **20 times in a loop under 3 CPU burners** (the PM recipe above) and show 20/20.

## Constraints and definition of done
- Stay in `backend/` and `docs/`.
- No `pragma: no cover`, no `mark.skip`, no lowered gates. Check the diff for destructive calls and ownerless tasks.
- `pre-commit run --all-files`, `just api-drift` and `just security` exit 0. Run `just check` **last** and paste its unfiltered tail.
- Final message: root cause (which hypothesis and the evidence), a **finding → fix → test** table, and the 20/20 loop output.
