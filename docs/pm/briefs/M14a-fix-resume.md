# Brief: M14a-fix-resume — finish after a host interruption

**From:** PM (Claude) · **To:** the same Codex engineer (resumed thread `01a09de0-daf6-7851-aa5a-2cff1dd2987b`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m14a`. **E2E port:** `TONEWATCH_E2E_PORT=8804` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## What happened
Your run was cut off at 21:28:59 on 2026-09-13 by a host reboot (`code-mode host closed its stdout`). **This was not your fault.** At that point you were fixing the last `just check` failures: the atomic secret writer's returned bytes differed from the persisted file on Windows. All your edits are still in the worktree.

## Required
1. **Re-read the full brief** at `C:\Users\beanie\Documents\Proj\tonewatch\docs\pm\briefs\M14a-fix.md`. Its items 1–4, the evidence rule and the Definition of done all still apply.
2. **Check the worktree** (`git status`, `git diff --stat`) against what you remember doing. Don't assume an edit landed; confirm it in the file.
3. **Finish the remaining failures,** then run the gates in order: `just check`, then `just e2e` (port 8804), then `just ci-local`.
4. **Report with the evidence rule from `M14a-fix.md`:** for each numbered item, the red-first line, the passing line and a diff excerpt with file:line. Also paste `git diff origin/main -- backend/tests/unit/test_s4_security.py`, which must be empty. If something remains unfinished, list it precisely.

**Standing rules unchanged:** never edit `docs/pm/**` or `PLAN.md`; never edit existing security tests to match new behaviour; never `git add`, commit or push; add no dependencies.
