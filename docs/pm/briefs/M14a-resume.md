# Brief: M14a-resume — finish and verify the live restream

**From:** PM (Claude) · **To:** the same Codex engineer (resumed thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m14a`. **E2E port:** `TONEWATCH_E2E_PORT=8804`.

## What changed
Your run was blocked by the environment, not by your code. That was the PM's fault: the worktree hadn't been set up. The PM has now:
- synced `backend/.venv` with CPython **3.13.13** (all groups)
- installed `web/node_modules` from the lockfile

**If `uv` still reports** `Missing expected target directory for Python minor version link` inside your sandbox, run every `just`/`uv` command with this set (it worked for another engineer tonight):
`UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`

On PowerShell, set `$env:UV_PYTHON` first. On cmd, use `set UV_PYTHON=...&& just check`.

## Required
1. Re-read `docs/pm/briefs/M14a-live-restream.md`. **Its Required section and Definition of done still apply in full**; nothing is waived.
2. Run the PyAV incremental-MP3 spike test first. If it fails, fix the implementation or record the real finding in ADR 0011 before building further.
3. Run the whole test suite and fix every failure in your code. Don't weaken tests or gates.
4. Run `just gen-api` and commit nothing; the drift check must pass.
5. **Measure** encoder CPU and latency on this host (per 100 ms frame, p50/p95) and put the numbers in ADR 0011, replacing any "intended" figures.
6. Confirm by test, not description: the stalled-listener latency test, token tests (expired, tampered, wrong source, missing, after secret rotation), caps (503), 404 when disabled, no encoder with zero listeners, and the log-capture test proving the token never appears in logs, including uvicorn access logs.

## Definition of done
Exactly as in `M14a-live-restream.md`:
- `just check` and `just ci-local` pass (port 8804), with the summary lines pasted.
- PROGRESS entries are marked `[~] PENDING-REVIEW`.
- The report covers the measured numbers, the token format and verification path, and every changed file.

**Standing rules unchanged:** never edit `docs/pm/**` or `PLAN.md`; never commit or push; add no dependencies.
