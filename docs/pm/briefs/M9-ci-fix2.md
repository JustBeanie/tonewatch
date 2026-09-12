# Brief: M9-ci-fix2 — image size budget + service stop semantics

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high
**Work dir:** worktree `tonewatch-m9ci2` (branch `m9ci2`, based on `origin/main` `f638f50`, which includes M9-ci-fix `9d5e0ef`)

## Situation
M9-ci-fix worked for three of the problems. On GitHub for `9d5e0ef`:
- The Windows service starts and `/readyz` answers.
- `runtime-export` passes.
- Docker `trivy`, `smoke`, `e2e-container` and `dast` pass.
- CI and Security pass.

Two jobs still fail. Fix both at their root cause and never weaken a gate. The 350 MB budget is a `PLAN.md` done criterion, so you may not raise it.

### G1: Docker `size`: the image is 376,986,832 bytes against a 350 MB budget
- **Before:** 347.2 MB.
- **Cause:** `apt-get upgrade -y` in the runtime APT layer rewrites every upgradable package from the base image, and the old copies stay in the lower layer. That costs about 30 MB.
- **Constraint:** the base digest `python:3.13-slim@sha256:9d2e5553…` is still upstream-current. The PM re-checked at 13:55, so the fixed Debian packages must still come from our layer.
- **Required approach:** do both of the following, and explain the estimated byte impact of each in your report.
  1. **Targeted upgrade.** Replace the blanket `apt-get upgrade` with a targeted `apt-get install --only-upgrade --no-install-recommends -y` of exactly the packages Trivy flagged: `gzip`, `libpcre2-8-0`, `libsqlite3-0`, `perl-base`.
     - Keep the rule written in `docker/README.md`: drop this once the upstream digest includes the fixes.
     - Add a guard so a future Trivy finding cannot silently pass: CI already runs Trivy with `--exit-code 1`, so just keep the list documented next to the command.
  2. **Win back headroom elsewhere.** The targeted upgrade alone likely adds about 10 MB, mostly `perl-base`.
     - In the **builder** stage, strip debug symbols from shared objects in `/opt/venv` with `strip --strip-unneeded` over `*.so*`, skipping files that fail.
     - Also delete test suites and `__pycache__` from the venv (numpy/scipy `tests/` directories), if not already trimmed.
     - Look first at what M8's builder-stage trim already removes (see `docker/README.md` and the Dockerfile), and don't duplicate it.
     - Nothing the app imports at runtime may be removed. CI `smoke` (import walk), `e2e-container` and `dast` are the proof.
     - If `binutils` is needed for `strip`, install it in the builder stage only.
- **Docker in your sandbox:** it is unavailable. Reason about sizes from package metadata (`apt-cache show` sizes are not available offline either, so give estimates and say so). The PM verifies on the CI rerun. Keep hadolint green, with same-line justifications per `AGENTS.md` if a rule fires.

### G2: Windows `service-lifecycle`: `service stop` returns before the service is actually stopped
- **Log:**
  ```
  service ToneWatch: install succeeded
  service ToneWatch: start succeeded
  service ToneWatch: stop succeeded
  throw "service did not stop cleanly"   # $status = & $exe service status; $LASTEXITCODE -ne 0 -or $status -notmatch "stopped"
  ```
- **Cause:** `tonewatch service stop` reports success as soon as the stop *request* is accepted, while SCM is still in `STOP_PENDING`, so the immediate `service status` does not print `stopped`.
- **Fix (product, not the workflow):**
  - `tonewatch service stop` waits until SCM reports `STOPPED`, with a bounded timeout of about 30 s. Use `win32serviceutil.WaitForServiceStatus` or poll `QueryServiceStatus`.
  - It exits non-zero with a clear message on timeout.
  - Make `service start` symmetric: wait for `RUNNING` within a bounded timeout.
  - `service status` must print the exact state name and exit 0 whenever the service exists: `running`, `stopped`, `start_pending`, `stop_pending` and so on.
- **Tests:** unit tests with the fake service manager for:
  - stop waits through `STOP_PENDING` to `STOPPED`
  - stop times out and exits non-zero
  - start waits to `RUNNING`
  - status prints each state name
- Keep the workflow's assertions as they are. They are correct once the CLI blocks properly.
- **Also:** `tonewatch.log` was 0 bytes in the CI data dir after a start/ready/stop cycle. Confirm the service writes at least a startup and a shutdown line to its log file when stdio is detached, and add a test.

## Standing rules
- Never edit `docs/pm/**`.
- Never weaken a gate: no budget raise, no skips, no `|| true` on assertions.
- Never fetch, commit or push.
- Don't bump unrelated pins.

## Definition of done
- `just check` passes. Paste the tail.
- `just ci-local` with `TONEWATCH_E2E_PORT=8798` reaches e2e. If the Windows Playwright launcher hangs only in teardown after all specs pass, say so exactly.
- The report maps G1 and G2 to their changes and tests, gives estimated byte savings or costs per G1 step, and lists what only CI can verify.
