# M8-fix2: make the image jobs pass on CI (size, trivy, container startup, gitleaks)

**Resuming the M8 thread on luna·high.** The PM has already pushed CI fixes and diagnostics (see the latest `ci(docker)` commit on `main`). Work from current `main`.

**HARD RULES** (from `AGENTS.md`):
- Never edit `docs/pm/**`.
- Never weaken a gate: no raising the 350 MB budget, no trivy `--ignore` / `.trivyignore` for fixable HIGH or CRITICAL findings, no skipping e2e specs, and no gitleaks allowlist broader than the proven false-positive line.
- Never delete or overwrite files outside scope.

## Evidence from CI (diagnostics run on `3ff4057`)
- 🚨 **Root cause of the smoke and e2e-container failures is a packaging bug, not Docker.**
  - Both jobs crash with `ModuleNotFoundError: No module named 'httpx'`.
  - `backend/src` imports **`httpx`** (webhook alerts; the stream redirect probe) and **`certifi`** (stream TLS `ca_file`). `httpx` is only in the **dev** dependency group, and `certifi` isn't in the runtime lock at all, so `uv sync --no-dev` drops both.
  - Local tests always install dev deps, which is why this was invisible.
  - **Fix:** add both as runtime `dependencies`, then run `uv lock`.
  - **Guard:** add a non-Docker CI job or test that installs **only** runtime deps into a fresh environment (for example `uv venv` + `uv pip install --no-deps -r <(uv export --no-dev)` + the project wheel) and imports every module under `tonewatch`. Any future dev-only runtime import must fail fast in normal CI.
  - Don't run `uv run --no-dev` in the main checkout; it strips the dev environment.
- **Size is 353,979,998 bytes (354 MB) against a 350 MB budget.**
  - `docker history`: the `/opt/venv` COPY is 218 MB, apt packages 9.5 MB, python base layers about 48 MB.
  - Adding `httpx` and `certifi` adds a little, so plan for roughly 10 MB of real savings.
- **Trivy python-pkg: 2 fixable HIGH findings.** Earlier run: `msgpack 1.1.2→1.2.1` and `setuptools 70.3.0→78.1.1`. The venv rows list 0 findings each, so they sit in the base image's `/usr/local/lib/python3.13/site-packages` (pip-vendored msgpack, setuptools). Confirm with the full trivy table.
- **Gitleaks is already resolved by the PM.** The finding was a quoted example header in a PM brief (`docs/pm/briefs/M8-fix.md:61`, rule `curl-auth-header`). The PM reworded the brief and added an exact-fingerprint `.gitleaksignore`. **Don't touch gitleaks config.**
- `build-amd64` and `build-arm64` **pass**. `compose-config`, the smoke entrypoint and actionlint were fixed by the PM.
- **`size` fails:** the image is over 350 MB (compressed artifact 119 MB). The diagnostics run prints the exact size and `docker history`.
- **`trivy` fails** with 2 fixable HIGH findings:
  - `msgpack 1.1.2 → 1.2.1` (GHSA-6v7p-g79w-8964)
  - `setuptools 70.3.0 → 78.1.1` (CVE-2025-47273)

  Neither package is in `backend/uv.lock` or the project's runtime tree (`uv tree --no-dev --invert`). They come from the **base image**: pip vendors msgpack, and setuptools is present in the image.
- **`e2e-container` fails:** all 4 specs failed at their first `page.goto`, so the app in the container never served. The old readyz wait could not fail, which hid it. The diagnostics run now fails fast at readyz and dumps `docker logs tonewatch-e2e`.
- **`gitleaks` finds 1 leak** in commit `d05564e`. The PM's entropy scan suggests a false positive on `.github/workflows/release.yml` `googleapis/release-please-action@<sha>`: the generic-api-key rule sees "api" next to a high-entropy value. The diagnostics run prints the file, line and rule.

## Required
1. **Trivy clean.** Remove what the runtime doesn't need from the runtime stage: `pip`, `setuptools`, `wheel` and `ensurepip` (the app runs from `/opt/venv` and never installs packages). Do it in the same `RUN` layer as apt cleanup, or with a final cleanup layer that actually removes files, not a whiteout on top of a large layer. If a finding is in `/opt/venv` instead, fix the lock with `uv lock --upgrade-package <pkg>` and rerun `just check`. Prove the result with the CI `trivy` job, and locally list exactly which paths you removed and why nothing imports them (for example `rg -n "import (pip|setuptools|pkg_resources)" backend/src`).
2. **Size under 350 MB,** without raising the budget.
   - Use the CI `docker history` output to find the big layers.
   - **Likely wins:**
     - `--no-install-recommends` already set; check the apt list (does `rtl-sdr` drag in `libusb` docs or extras?)
     - `UV_COMPILE_BYTECODE` choices; strip `__pycache__` and tests from site-packages only if safe
     - don't copy the uv binary into the runtime
     - exclude web `node_modules` from anything copied
     - check whether `scipy` or `numpy` wheels drag in test suites removable by a documented `find … -path '*/tests' -prune` step. Import-check afterwards.
   - **Every removal** must be followed by the in-image import smoke (`tonewatch`, `tonewatch.api.spa`, `numpy`, `scipy.signal`, `av`, `sounddevice`) in the CI `smoke` job.
   - Document the final size and the biggest remaining layers in `docker/README.md`.
3. **Container starts and serves.** Fix the root cause shown by `docker logs tonewatch-e2e`.
   - **Candidates to check:**
     - read-only root fs writes (HOME, `.cache`, matplotlib/numba-style caches, uv/pip caches, `/tmp` usage)
     - `TONEWATCH_DATA_DIR` permissions on the named volume for UID 10001
     - the copied config referencing `/fixtures/fixture.wav`
     - `web_dist` missing from the installed package
   - Reproduce the startup path locally without Docker as far as possible: build a `--no-editable` venv copy, set `TONEWATCH_DATA_DIR` to a fresh directory and `HOME` to a read-only one, run `tonewatch serve`, then `curl /readyz`.
   - Add a regression test for the root cause if it's app code (for example "serve works when HOME is not writable").
4. **Runtime dependency closure (do this FIRST; it's the root cause of the smoke and e2e-container crashes).**
   - **Dependencies:** move `httpx` from the `dev` group to runtime `dependencies`, add `certifi` as a runtime dependency, then run `uv lock`. Check for any other module under `backend/src/tonewatch` that imports a package missing from `uv export --no-dev`. The PM found exactly these two; prove there are no more.
   - **Regression guard:** add a CI job in `ci.yml` (Linux, no Docker) that builds a clean environment with **only** runtime deps and the project installed non-editable, then imports every `tonewatch.*` module (walk the package with `pkgutil.walk_packages`). It must fail on a dev-only runtime import. Give it `timeout-minutes` and `permissions: {contents: read}`.
   - **Proof:** locally, run the same import walk in a throwaway venv outside the main checkout's `.venv`, and show it failing before the dependency fix and passing after.
   - **Don't touch gitleaks.** The PM handled it with an exact-fingerprint `.gitleaksignore`.

## Definition of done
- `pre-commit run --all-files`, `just api-drift`, `just security`, and `just e2e` (Chrome) exit 0. `just check` runs **last**; paste its unfiltered tail.
- **Final message:** a finding → root cause → fix → proof table, the exact image size reasoning, and the CI jobs the PM must watch: `size`, `trivy`, `smoke`, `e2e-container` and `gitleaks`, each with pass criteria.
