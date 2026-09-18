# Brief: M19h-fix2 — raise web branch coverage above 81 %

**From:** PM (Claude) · **To:** Codex engineer (resume your thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19h` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8846`.

## Status
- **Item 1:** the PM updated `backend/tests/unit/test_s4_security.py` line 729 to the keyset value (`"2"`, with a comment). That was a deliberate API change, so it is PM-owned. You were right to stop. Keep your `audit.py` without the fallback. Do **not** edit that S4 file.
- The PM verified that `test_s4_security.py` and `test_m19h_audit.py` pass.

## Required
- Web branch coverage is 80.48 %, but the brief required **at least 81 %**, a margin above the 80 % gate. Add **behavioural** Vitest tests for the untested branches of your new pages: `Credentials.tsx`, `Maintenance.tsx`, `Audit.tsx` and the new `shared.ts` formatters. Use the coverage report to find them, and test the error, empty and disabled paths. Never add tests that only execute lines without asserting behaviour, and never change coverage config.

## Evidence
- The coverage summary line before and after, and the new test names.
- `just check` fully green (pytest and Vitest counts), and `just ci-local` up to `api-drift` after `just gen-api`.
- **Honesty rule:** as always.

## Standing rules
- As in M19h. **Parallel engineers:** M19f and M19g are in backend files; stay in `web/**`.
