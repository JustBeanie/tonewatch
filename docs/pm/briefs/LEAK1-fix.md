# Brief: LEAK1-fix — explain the order-dependent audio-guard failure, and prove which test leaked

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b6fb-14c8-7d42-a014-8bea36ed3b7f`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-leak1` (your uncommitted work stays). `docs/pm/briefs/LEAK1-aiosqlite.md` still applies.

## PM findings
1. **The S4 failure is order-dependent and appeared only with your guard.**
   - The PM ran `backend/tests/unit/test_s4_security.py` alone in your worktree, with your `collect_garbage_after_test` fixture: **26 passed, 1 skipped**.
   - In your full guarded run, `test_tests_cannot_open_real_audio_devices` got a `PortAudioError` instead of the conftest's `AssertionError`. The baseline full run without the guard passed. So something that runs earlier, combined with the per-test `gc.collect()`, leaves `soundcard.sd.InputStream` unpatched, or makes the conftest's patch miss (a different `sounddevice` module object, a `sys.modules` swap, or a finalizer that re-imports or resets it).
   - This is a real isolation bug. Don't paper over it, and **don't edit `test_s4_security.py`**.
   - **Find it:** bisect the test order (run S4 after halves of the suite, e.g. `pytest <subset> backend/tests/unit/test_s4_security.py -p no:randomly`) until you have the minimal earlier test that triggers it. Then explain the mechanism with evidence: print `id(soundcard.sd)`, `sys.modules["sounddevice"]` identity and `soundcard.sd.InputStream` inside the failing test.
   - Fix the root cause in that earlier test (or in production code, if production code swaps the module), so the guard and S4 pass in the full order.
2. **The leaker was never proven.** Your report says the focused pre/post case "reproduced no aiosqlite warning", yet you changed `test_m19b_admin_alerts.py`.
   - Show evidence that `test_m19b_admin_alerts.py` was actually leaking: with your guard in place and the M19b change reverted, the guard fails **in that test**. Paste that output.
   - If it doesn't fail, keep looking. Run the full suite with the guard and without your M19b change, and let the guard name the leaking test(s).
3. **Measure overhead.** You gave a baseline of 578 s and a guarded run of 356 s. Those numbers can't compare like with like, since the guarded run is faster. Rerun both on an idle machine back to back and report both times. If per-test `gc.collect()` costs more than ~15 %, switch to a cheaper scope and say which.

## Evidence (the report is rejected without it)
- The minimal reproducer order for item 1, with its mechanism and fix (file:line).
- The guard failing in the leaking test before its fix (item 2), and passing after.
- Two consecutive full `just test` runs, both green, with summary lines and times, plus the before/after overhead.
- `just check` fully green, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in LEAK1. Never edit `test_s4_security.py` or add warning filters. **Parallel:** the PM is landing M19l (replay). Don't touch `api/routes/replay.py` or its tests; report a leaker there instead.
