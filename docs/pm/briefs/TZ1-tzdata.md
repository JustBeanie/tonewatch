# Brief: TZ1 — IANA time zones must work on Windows and in the slim Docker image

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-tz1` (branch `tz1`). **E2E port:** `TONEWATCH_E2E_PORT=8822` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Problem (found by the PM while reviewing M18b)
- `backend/src/tonewatch/config/models.py:~431` validates `MeshtasticTarget.timezone` with `zoneinfo.ZoneInfo(name)`.
- On Windows there's no system tz database, and the project doesn't depend on the `tzdata` package, so `ZoneInfo("UTC")`, `ZoneInfo("America/Denver")` and every other zone raise `ZoneInfoNotFoundError`. The M18b e2e run hit a 422 for `"UTC"`.
- The native Windows build (PyInstaller) therefore can't save any Meshtastic timezone.
- `python:3.13-slim` (the Docker base) may also lack `/usr/share/zoneinfo`. Verify this from `docker/Dockerfile` and the Debian slim package set; don't guess.
- `alerts/meshtastic.py:52` special-cases `"UTC"` only.

## Required
1. **Add `tzdata` as a runtime dependency** of `backend` (unconditional). This is PM-authorized: a pure data package under the Apache-2.0 licence, maintained by the CPython core team.
   - Update `uv.lock` with `uv lock`.
   - Confirm the licence passes the repo's licence checks (`just check` / security recipes).
   - Confirm `scripts/check_runtime_export.py` still passes.
2. **PyInstaller:** make sure the frozen Windows build contains the tzdata zone files.
   - Check whether `pyinstaller-hooks-contrib` already has a `tzdata` hook. If not, add `collect_data_files("tzdata")` to `packaging/windows/tonewatch.spec`.
   - Add a frozen smoke check to the `selftest` command (e.g. `tonewatch selftest imports` or a new `selftest tz` subcommand) that resolves `ZoneInfo("America/Denver")`, and call it in `windows.yml` `smoke`. Follow the style of the existing smoke steps.
3. **Remove the `"UTC"` special case** in `alerts/meshtastic.py` if it's now redundant. Keep the behaviour identical, and keep the golden tests unchanged.
4. **Web:** leave the M18b UI blank-timezone → `null` behaviour as is, and add no new UI.

## Mandatory tests (write first; show each failing before the fix where applicable)
- **A.** A unit test that `MeshtasticTarget(timezone="America/Denver")` and `timezone="UTC"` validate. It must fail on the host before adding `tzdata`; paste that failing line from your Windows run.
- **B.** An invalid zone (`"Mars/Olympus"`) still gives a validation error.
- **C.** A test that `importlib.metadata.distribution("tzdata")` is present in the runtime export (`uv export --no-dev`). Extend the existing runtime export check or its test.
- **D.** A render test where `America/Denver` gives the expected local `HH:MM` for a fixed UTC `detected_at`, both inside and outside DST.

## Gates and evidence (the report is rejected without it)
- A table mapping test name → letter, with each test's first-run result and its passing line.
- `just check` (pytest before and after), `just e2e` on port 8822, and `just ci-local` up to `api-drift`.
- `git diff --stat`, plus the `uv.lock` hunk for `tzdata` (name, version, source).
- State what you found about `/usr/share/zoneinfo` in the Docker base, with evidence.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` code and pasting that result. Don't cite sources you didn't read.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. No dependencies other than `tzdata`. Never weaken a gate.
