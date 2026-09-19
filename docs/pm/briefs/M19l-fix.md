# Brief: M19l-fix — make call replay meaningful (current vs draft on the same audio) and lift replay coverage

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b696-5d71-7810-92d7-c126a44d0921`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19l` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8854`. `docs/pm/briefs/M19l-replay.md` still applies.

## PM review
Good work: the tests A–E exist, `import_tones_cfg.py` is at 92.86 %, and the trimmed-recording limitation is documented. Two things remain. Write a failing test first for each, and paste its failing line as you go.

1. **Call classification is misleading.**
   - For calls, `replay.py` (~line 258) compares the **recorded** tone sets (`actual`) with what the **draft** detects on the **tone-trimmed** recording. The tones were cut out, so nearly every call classifies as `would_miss` for any draft, including an unchanged one. An operator reads that as "the draft breaks everything".
   - **Fix:** classify calls the same way as uploads: run the **current** config and the **draft** on the same audio, and classify the draft against the current result (`would_detect` / `would_miss` / `new_detection` / `unchanged`).
     - Keep the recorded tone sets in the item as a separate `recorded` field, for context.
     - On voice-only call audio this becomes a useful **false-positive check**: a draft that starts detecting on voice shows up as `new_detection`.
   - Update the `limitations` text and `docs/guide/admin.md` to say exactly that: "Stored call recordings are tone-trimmed voice clips. Replaying them checks that the draft doesn't start triggering on voice traffic. Use uploaded WAVs to test tone detection."
   - **Tests:**
     - an **unchanged** draft on call recordings gives zero `would_miss` and zero `new_detection`
     - a deliberately loose draft (e.g. a very wide tolerance, or a tone set matching the voice-like fixture's dominant frequency) on a voice call recording gives `new_detection`
     - `recorded` carries the stored tone sets
2. **`api/routes/replay.py` coverage is 90.82 %**, under the required 1 % margin above its 90 % gate. Add **behavioural** tests for its uncovered branches (read the coverage report): decode failures, the per-item timeout, the cap boundary (an item that would cross the cap is skipped and reported), an unknown upload id, and an expired upload. Get it to at least 91.5 %. No production changes unless a test exposes a bug.
3. **Your `sources` line was 90.78 %, but main is at 91.26 %.** You didn't touch `sources/`, so say whether a sources test was skipped or failed in your sandbox run. The PM's host gate will confirm.

## Evidence (the report is rejected without it)
- A table mapping items 1–2 to their tests, with the failing line before the fix and the passing line after.
- `just check` fully green with the pytest count, plus the `check_package_coverage.py` lines for `api/routes/replay.py`, `sources` and `dsp`.
- `just ci-local` up to `api-drift` after `just gen-api`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19l. **Parallel engineer LEAK1** is in test hygiene: `backend/tests/conftest.py` and whichever tests leak aiosqlite connections. Don't touch `backend/tests/conftest.py`. If your new tests create engines, dispose them.
