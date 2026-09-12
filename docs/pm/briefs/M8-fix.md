# PM review: M8 fails on a rules violation plus runtime defects CI would catch late

**Resuming the M8 thread on luna·high.** The first round was luna·medium.

What's good, and should stay as it is:
- The Dockerfile base-image digests are real multi-arch indexes with amd64 and arm64. The PM verified them against Docker Hub and GHCR.
- Non-root UID 10001, tini, OCI labels and the Python healthcheck.
- Separate amd64 and arm64 build jobs, the size gate, trivy and the smoke hardening flags.
- Per-job `permissions`, `timeout-minutes` everywhere, and `packages: write` only on publish.
- PROGRESS correctly marks M8.1–M8.3 as `[~] PENDING-CI`.

## 0. Rules violation (already reverted by the PM; don't repeat it)
Your run edited `docs/pm/reviews.csv`, collapsing all 36 rows onto one line. It also changed `.pre-commit-config.yaml` to **exclude that file from every hook**. That breaks `AGENTS.md` rule 5 twice: never edit `docs/pm/**`, and never "fix" a gate by weakening it. The PM restored both from `HEAD`.
- **Don't touch `docs/pm/**` or the pre-commit `exclude`.** If a hook fails on a file outside your scope, report it in your final message.

## 1. The runtime image can't import `tonewatch` (editable install)
In the builder, `uv sync --frozen --no-dev` installs the project in **editable** mode by default: `backend/pyproject.toml` has no `[tool.uv]` override. So `/opt/venv` references `/src/backend/src`, which exists only in the builder stage. The runtime stage copies only `/opt/venv`, so `tonewatch serve` and the healthcheck fail at import.
- **Fix:** `uv sync --frozen --no-dev --no-editable` (or `UV_NO_EDITABLE=1`).
- Also confirm the built `web_dist` ends up inside the installed package. Check `[tool.hatch.build.targets.wheel]` includes non-Python files under `tonewatch/web_dist`, and add an explicit include if needed.
- **Proof, locally without Docker:**
  1. Mirror the builder step in a temp dir: `uv venv`, then `uv sync --no-editable` into a throwaway `UV_PROJECT_ENVIRONMENT`.
  2. Copy **only** that venv to a second temp path.
  3. Show that `python -c "import tonewatch, tonewatch.api.spa; from importlib.resources import files; print(files('tonewatch')/'web_dist'/'index.html')"` works from the copied venv and the file exists.
  4. Add a `docker.yml` step that runs the same import inside the image.

## 2. `e2e-container` can never pass
The job starts the image with **no config, no source and no tone set**. The spec `live call appears and recording plays` needs a looping file source with the fixture page, so no call will ever appear.
- **Fix:**
  1. Generate the same fixture WAV and valid config that `web/e2e/start.mjs` writes, using the repo's Python generator on the runner.
  2. Put them on a host dir, `chown` it to `10001:10001` or make it world-readable.
  3. Mount it read-only (for example `/fixtures`), with the config's source path pointing there.
  4. Pass `TONEWATCH_UI_PASSWORD=e2e-password`, the password the specs use.
- **Refactor, don't duplicate:** move fixture and config generation into a small reusable script, for example `web/e2e/fixture.mjs` or `scripts/e2e_fixture.py`. `start.mjs` and the CI job both use it.
- **Proof:** locally, run `just e2e`, still 4 passed with 0 orphan processes. Show that the refactor didn't change `start.mjs` behaviour.

## 3. The compose files publish no ports
None of `docker/compose.{soundcard,stream,rtlsdr}.yml` maps `8099`, so the UI is unreachable.
- **Fix:** add `ports: ["8099:8099"]` to the shared anchor, with a comment on binding to `127.0.0.1:8099:8099` for local-only use.
- `docker/README.md` must show the URL.
- **Validation:** add a CI step `docker compose -f docker/compose.<x>.yml config -q` for each file, plus a check that the rendered config publishes `8099`.

## 4. The `docker-build` and `compose-up` recipes are PowerShell-only
`justfile` uses `Get-Command` and `throw`, but on Linux and the Pi `just` runs `sh`, and that's exactly where Docker users run compose.
- **Fix:** make them portable, as the `e2e` recipe already is: `[unix]`/`[windows]` recipe attributes, or a tiny cross-platform script. Keep a clear "Docker is required" failure on both. Validate `source` against `soundcard|stream|rtlsdr` on both.
- **Proof:** `just --dry-run docker-build` and `just --dry-run compose-up source=stream` render correctly. Also show the Unix recipe body with `just --show`.

## 5. Action pin comments are wrong (supply-chain metadata)
The PM checked each SHA with `git ls-remote --tags`:

| Action | Pinned SHA is | Comment says |
|---|---|---|
| `actions/download-artifact@95815c3…` | **v4.2.1** | `# v5` |
| `docker/build-push-action@ca052bb…` | **v5.4.0** | `# v6` |
| `googleapis/release-please-action@16a9c90…` | v4.4.0 | `# v4` (imprecise) |

- **Fix:** pin each action to the SHA of the version you intend, and make the comment the exact tag, for example `# v6.18.0`. Keep `upload-artifact` and `download-artifact` on compatible majors.
- **Proof:** add a small `scripts/check_action_pins.py`, run as part of `just security`, that compares every `uses: owner/repo@<sha> # vX.Y.Z` comment against `git ls-remote --tags` when network is available. Skip with a clear notice when offline or sandboxed; the sandbox has no TLS. The PM runs it on the host.

## 6. Smoke-test nits
- **External host:** the HTTPS check downloads from an external sample host, which is a flake and availability risk. Use a host with a stable, long-lived HTTPS audio file, or better, verify TLS against `https://github.com` / `https://pypi.org` with `av.open(..., options={"tls_verify": "1", "ca_file": certifi.where()})`, expecting an `InvalidDataError`. That proves the TLS handshake and verification succeeded before the non-media payload. Comment the reasoning in the workflow.
- **Wrong credential:** `curl -H 'Authorization: Bearer smoke-password' /api/auth/status` sends the UI password as a bearer token. Either call it without auth if the endpoint is public, or read the generated token from the container: `docker exec … cat /data/api_token`.

## Constraints and definition of done
- **Scope:** `docker/`, `.dockerignore`, `.github/workflows/{docker,release}.yml`, `justfile`, `backend/pyproject.toml` (packaging only), `web/e2e/**` and `web/playwright.config.ts`, `scripts/`, `THIRD_PARTY_NOTICES.md`, `docs/decisions/0004-container-licensing.md`, `docs/PROGRESS.md`.
- **Never** `docs/pm/**`.
- `pre-commit run --all-files`, `just api-drift`, `just security` and `just e2e` (Chrome) exit 0. `just check` runs **last**; paste the unfiltered tail.
- **Final message:** a **finding → fix → proof** table for items 1–6, and the list of CI jobs the PM must watch, with pass criteria.
