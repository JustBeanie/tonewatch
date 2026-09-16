# Brief: REL1 — attach the Windows zip and checksums to every GitHub release

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-rel1` (branch `rel1`). **E2E port:** `TONEWATCH_E2E_PORT=8818` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest errors with `PermissionError ... pytest-of-Beanie`, use `--basetemp` pointing **outside** the repo (for example `$env:TEMP\tonewatch-rel1-pytest`), never inside `backend/`.
**Git:** never write git state (no add/commit/stash/push).

## Problem
The plan requires `release.yml` to attach the Windows zip and checksums to each release. Today the releases for v0.3.0 and v0.4.0 have **zero assets**:
- `windows.yml` builds `tonewatch-windows.zip` and only uploads it as an Actions artifact.
- `release.yml` publishes the Docker image and nothing else.

## Required design
1. **Make `windows.yml` reusable.**
   - Add an `on.workflow_call` trigger with a string input `release_tag` (default `""`).
   - Keep every existing trigger, path filter, job and smoke step unchanged in behaviour.
   - When `release_tag` is set, the build must check out that tag (`ref:`), not the default ref, in **every** job that checks out code.
   - Concurrency must not let a release call cancel, or be cancelled by, a push run. Include the tag or `github.event_name` in the group when called.
2. **Add an `attach` job in `windows.yml`.**
   - It runs only when `inputs.release_tag != ''`.
   - It `needs` **all** verification jobs (`build`, `smoke`, `service-lifecycle`, `https`), so an unverified zip is never attached.
   - Validate the tag against `^v[0-9]+\.[0-9]+\.[0-9]+$` exactly as `release.yml` does, and fail otherwise.
   - Rename the asset to `tonewatch-<tag>-windows-x64.zip`, generate `SHA256SUMS.txt` (`sha256sum` format: `<hex>  <filename>`), and upload both with `gh release upload "$TAG" ... --clobber`.
   - Permissions: `contents: write` on this job only. Everything else stays least-privilege. Use `GH_TOKEN: ${{ github.token }}` and `--repo ${{ github.repository }}`.
   - Run it on `ubuntu-latest`, since it only downloads the artifact and uploads.
3. **Call it from `release.yml`.**
   - Add a job `windows` with `uses: ./.github/workflows/windows.yml` and `release_tag` set to the same tag expression the `publish` job uses.
   - Use the same `if:` as `publish` (release-please created a release, or `workflow_dispatch` re-publish).
   - Grant `permissions: {contents: write}` at the calling job, the minimum the called `attach` job needs.
   - Don't make `publish` depend on `windows` or vice versa; a Windows failure must not block the image.
   - `workflow_dispatch` with an existing tag must attach assets to that release. That's how the PM will backfill v0.4.0.
4. **Docs.**
   - Update the release/install docs that mention the Windows build (grep `docs/` for `windows` and `release`) to say where the zip and `SHA256SUMS.txt` live and how to verify them (PowerShell `Get-FileHash -Algorithm SHA256`).
   - Keep the docs short.
5. **Keep `backend/uv.lock` in step with release versions.**
   - The v0.4.0 release PR bumped `backend/pyproject.toml` to 0.4.0 but left `backend/uv.lock` at `version = "0.3.0"` for the `tonewatch` package. Any `uv sync` then rewrites the lock, and the pre-commit ruff hook fails with "files were modified". The PM fixed the lock by hand while landing M19b.
   - `release-please-config.json` already has an `extra-files` entry for this, but it did nothing. Likely cause: `extra-files` paths are relative to the package directory (`backend`), so `backend/uv.lock` resolves to `backend/backend/uv.lock`. The jsonpath filter syntax may also be wrong for release-please's TOML updater. Confirm both against the release-please documentation or source, fix the entry, and cite what you relied on in the report.
   - Prove the jsonpath: write a small unit test or script check that reads `backend/uv.lock` with `tomllib` and asserts the `tonewatch` package version equals `backend/pyproject.toml`'s `project.version`, and wire that check into `just check`. Show it failing against a temporary copy with a mismatched version.

## Constraints
- **Pin every action by full SHA** with a version comment, reusing the SHAs already in the repo. Add no new third-party actions; `gh` is on the runner.
- Don't add a new workflow file. A new file is auto-enabled on GitHub, and the repo avoids that.
- No `pull_request_target`. Never expose `contents: write` to `pull_request` runs: the `attach` job must be impossible to reach from a PR or push trigger.
- No shell injection: pass the tag via `env:`, never interpolate `${{ }}` directly inside `run:` scripts.

## Gates (evidence required; the report is rejected without it)
- `actionlint` on both workflows (it runs through pre-commit in `just ci-local`). Paste its result.
- `just check`, then `just ci-local` up to at least `api-drift`. Paste the final lines.
- A table showing, for each trigger (`push` main, `pull_request`, `schedule`, `workflow_dispatch` on windows.yml, `workflow_call` with a tag), which jobs run and whether `attach` can run. Justify each row from the `if:` expressions you wrote.
- Show the exact `git diff --stat` and the full diff of both workflow files.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same command on `origin/main` code and pasting that result. Don't describe work you haven't done.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new dependencies. Never write git state or touch anything outside the worktree.
