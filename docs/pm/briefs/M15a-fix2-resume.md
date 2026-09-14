# Brief: M15a-fix2-resume — finish after a host interruption

**From:** PM (Claude) · **To:** the same Codex engineer (resumed thread `01a09968-2163-7eb3-b3e5-8a30671139fa`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m15a`. **E2E port:** `TONEWATCH_E2E_PORT=8803` (leave `TONEWATCH_E2E_URL` unset; in cmd, write `set TONEWATCH_E2E_PORT=8803&& just e2e` with no space before `&&`).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## What happened
Your run was cut off at 21:28:59 on 2026-09-13 by a host reboot. **This was not your fault.** At that point you had just fixed typecheck errors in test doubles (typed casts) and were about to run typecheck, lint and the full suite. All your edits are still in the worktree.

## Required
1. **Re-read the full brief** at `C:\Users\beanie\Documents\Proj\tonewatch\docs\pm\briefs\M15a-fix2.md`. Requirements 1–9 and its Definition of done all still apply.
2. **Check the worktree** (`git status`, `git diff --stat`) against what you remember. Confirm every change in the file itself; don't assume it landed.
3. **Finish:** `just typecheck` and `just lint`, then `just check`, then `just e2e` (port 8803), then `just ci-local`.
4. **Report:** a table mapping requirements 1–9 to test names with their passing lines, plus the pytest count before (412) and after, vitest, and dsp/pipeline coverage. If something remains unfinished, list it precisely, as you did before.

**Standing rules unchanged:** never edit `docs/pm/**` or `PLAN.md`; never weaken a gate; never `git add`, commit or push.
