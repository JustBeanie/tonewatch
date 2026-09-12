# Brief: M9-ci-fix — first real GitHub runs of Windows + Docker workflows

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high
**Work dir:** worktree `tonewatch-m9ci` (branch `m9ci`, based on `origin/main` `bd9a200`)

## Situation
GitHub Actions was re-enabled after the repo went public. This was the first cloud run of M9's `windows.yml` (run 34711905162) and of `docker.yml` since the S5 changes (run 34711903651). CI, Security and Security (dependencies) are green. There are three failures. Fix each at its root cause, prove it locally with tests, and never weaken a gate.

### F1: Windows `service-lifecycle`: the service crashes on start
- **Symptom:** `service install` and `service start` succeed, but `/readyz` never answers and the service ends up `stopped`.
- **Cause:** the Application event log shows:
  ```
  File "tonewatch\service.py", line 236, in serve_until_stopped
  File "uvicorn\config.py", line 297, in __init__
  File "uvicorn\config.py", line 392, in configure_logging
  File "logging\config.py", line 936, in dictConfig
  ValueError: Unable to configure formatter 'default'
  ```
  Under the Windows service host, `sys.stdout` and `sys.stderr` are `None`. uvicorn's default `LOGGING_CONFIG` formatter calls `isatty()` on them and fails.
- **Fix:** in `serve_until_stopped`, do not let uvicorn install its own logging config in service mode. Pass `log_config=None` so logging stays with structlog, or pass a config with no stream handlers. Also check that no other code path writes to `sys.stdout` or `sys.stderr` under the service, including structlog's configured logger factory and any `print`-like output. If output would go to a `None` stream, route it to a file under the data dir or to the event log.
- **Test:** a unit test that sets `sys.stdout = None` and `sys.stderr = None` (monkeypatch) and runs `serve_until_stopped` with a fake `server_factory`. The test must fail on current `main` and pass after the fix. Add a similar guard test for the service's logging setup.

### F2: Windows `runtime-export` job fails on a correct lockfile
- **Symptom:** `uv export --no-dev` contains `pywin32==312 ; sys_platform == 'win32'`. It is correctly a marker-gated runtime dependency of the service wrapper, but the step's `! grep -Eiq '...pywin32...' runtime.txt` rejects it.
- **Intent of the check:** the Linux/Docker runtime must not install Windows-only or packaging-only packages.
- **Fix:** make the check express that intent precisely.
  - `pyinstaller`, `altgraph` and `pefile` must be absent from the runtime export entirely.
  - `pywin32` and `pywin32-ctypes` may appear **only** with a `sys_platform == 'win32'` marker.
  - Better still, also prove what a Linux install resolves. For example, use `uv pip compile --python-platform linux` or `uv export` with a platform filter, if uv supports it offline from the lock. Assert that no `pywin32*` package resolves.
  - Keep the step self-contained bash with no `|| true` masking on the assertions. Move the logic into a small script under `scripts/` if that makes it clearer, and add a unit test for it.
  - Run it locally against the real lockfile.

### F3: Docker `trivy` fails on fixed Debian CVEs in the base image
- **Symptom:** Trivy (`--severity HIGH,CRITICAL --ignore-unfixed`) reports 12 vulnerabilities in the runtime image, all with fixed versions in `trixie-security`:
  - `gzip` 1.13-1 → 1.13-1+deb13u1
  - `libpcre2-8-0` 10.46-1~deb13u1 → ~deb13u2
  - `libsqlite3-0` 3.46.1-7+deb13u1 → +deb13u2
  - `perl-base` 5.40.1-6 → 5.40.1-6+deb13u1
- **Cause:** the pinned `python:3.13-slim@sha256:9d2e5553…` is **still the current upstream digest**; the PM checked the registry today. Re-pinning alone therefore cannot fix this.
- **Fix:** upgrade the already-installed OS packages in the runtime stage's existing `apt-get` layer, in the same `RUN` so no extra layer or cached lists remain. For example, run `apt-get upgrade -y` (not `dist-upgrade`) before the install and keep the `rm -rf /var/lib/apt/lists/*` cleanup.
  - Apply the same upgrade to the builder stage only if it matters for the final image; it doesn't if nothing is copied from it.
  - The change must pass hadolint in pre-commit. If a rule fires, justify it on the same line per `AGENTS.md`; do not disable it globally.
  - Keep the image under the **350 MB** budget. The last image was 347.2 MB, so check the delta. If Docker is unavailable in your sandbox, state that exactly; the PM verifies with the CI rerun.
  - Add a line to the relevant ADR or `docker/README.md` explaining why the runtime stage upgrades base packages, and when the step can be dropped (once the upstream digest includes the fixes).

## Standing rules
- Never edit `docs/pm/**`.
- Never weaken a gate: no skips, deselects, exclusions, `|| true` on assertions, or lowered thresholds.
- Never fetch, commit or push.
- Don't bump unrelated action or image pins.

## Definition of done
- There is a regression test for F1 and for F2's check logic.
- `just ci-local` exits 0 with `TONEWATCH_E2E_PORT=8797`. Paste the tail. If api-drift or e2e is blocked by the sandbox, state that exactly.
- `actionlint` and `zizmor` pass on the changed workflow via `just security` or pre-commit.
- The final message maps F1–F3 to their fixes and tests. It lists what you could not verify locally (Windows service host, Docker build/Trivy) so the PM checks those in the CI rerun.
