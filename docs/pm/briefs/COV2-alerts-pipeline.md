# Brief: COV2 — main CI is red: alerts coverage 89.96 % on Linux; pipeline margin thin

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-cov2` (branch `cov2`). **E2E port:** `TONEWATCH_E2E_PORT=8834`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Problem (PM evidence)
GitHub CI on `main` at `ef88068`: `test-python (ubuntu-latest)` fails `check_package_coverage.py` with **`alerts: 89.96% (minimum 90.00%)`**.
- The Windows host run of the same code measured alerts at **90.24 %**, so some alerts lines only execute on Windows (platform branches such as the script target, process handling or path logic). Linux CI misses them.
- `pipeline` is also near the gate: 95.30 % on the host and 95.53 % on CI, after M17a added CAD wiring to `pipeline/supervisor.py`.

## Required
1. **Find the Linux-only gap.** Run coverage with the JSON report on the host, and read the code for `sys.platform`/`os.name` branches in `backend/src/tonewatch/alerts/**`. List the alerts lines that are platform-conditional or uncovered.
   - Write **platform-independent behaviour tests** for them: monkeypatch `sys.platform`/`os.name` or inject the platform seam, so the branches execute on every OS.
   - Also cover the new `CallEnriched` paths in `alerts/dispatcher.py` and `alerts/mqtt.py` if they're under-tested.
   - The goal is **alerts ≥ 91.5 %** on the host, with the platform branches exercised regardless of OS.
2. **Pipeline:** add behaviour tests for the CAD wiring in `pipeline/supervisor.py`: `cad_correlation` start, stop and reload on config change; feed runner add, remove and disable via hot-apply; and error paths. The goal is **pipeline ≥ 96.5 %**.
3. **Never lower a gate**, add `pragma: no cover`, or exclude files. Tests only, unless a test exposes a real bug; if so, show that failing test first.
4. **Don't touch** `api/audit.py`, `api/deps.py`, `logging.py` (a parallel engineer is working there) or `web/**` (another engineer).

## Evidence (the report is rejected without it)
- The list of platform-conditional and uncovered alerts lines found, with file:line.
- A table mapping each new test to the lines or behaviour it pins, with its first-run result.
- **The `check_package_coverage.py` output from two consecutive `just test` runs** (alerts and pipeline lines).
- A **simulated Linux check**: run the new platform tests with `sys.platform` patched to `linux` and paste that they pass.
- `just check` green, then `just ci-local` up to `api-drift`. `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. No new dependencies. No subdirectory `conftest.py`. No real sockets in tests.
