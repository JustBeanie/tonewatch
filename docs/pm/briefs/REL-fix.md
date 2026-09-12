# Brief: REL-fix — make release-please build releases, and gate image publish on Trivy

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high
**Work dir:** worktree `tonewatch-rel` (branch `rel`, based on `origin/main`). **E2E port:** `TONEWATCH_E2E_PORT=8802`.

## Situation
- **User decision (2026-09-12):** v0.2.0 is released as a **tag + GitHub release only**, with no image. The PM created tag `v0.2.0` at `e3397e6` and relabelled PR #1 `autorelease: tagged`. **v0.3.0, cut from current `main`, will be the first published (still private) GHCR image.**
- **Why release-please never built a release.** In release-please v17.1.3 `strategies/base.ts` `buildRelease`, a standalone release PR is accepted only when `normalizeComponent(branchName.component) === normalizeComponent(getBranchComponent())`.
  - Our config (`release-please-config.json`: a single package `backend` with `component: "backend"`, `include-component-in-tag: false`, `separate-pull-requests: false`) creates the grouped PR branch `release-please--branches--main`, which has **no** component.
  - `getBranchComponent()` returns `"backend"`, so every run logs `PR component: undefined does not match configured component: backend` and builds 0 releases.
- **Why the release workflow runs no image scan.** `release.yml` `publish` pushes, signs and attests the image without any Trivy scan, while `docker.yml` does run one. A release could therefore publish an image that CI would have failed.
- **Stale lockfile.** The release-please version bump does not update `backend/uv.lock`, so the lock goes stale right after a release. That was the carryover item.

## Required
1. **release-please config.** Make future release PRs produce releases.
   - Set `"separate-pull-requests": true`. With a single component-named package, the PR branch then becomes `release-please--branches--main--components--backend`, matching `getBranchComponent()`.
   - Keep `include-component-in-tag: false`, so tags stay `vX.Y.Z` and `release.yml`'s `backend--tag_name` output and vX.Y.Z validation keep working.
   - Explain in a short ADR `docs/decisions/00NN-release-please-component.md` (next free number) the root cause above and why this setting fixes it. Cite the exact release-please version the action pins.
   - **Verify offline, as far as possible.** Add a unit test that loads `release-please-config.json` and `.release-please-manifest.json` and asserts:
     - `separate-pull-requests` is true
     - `include-component-in-tag` is false
     - the package path `backend` has `component: "backend"`
     - the manifest version is valid semver.

     If you can install and run `release-please` locally without network writes, e.g. `npx release-please@<pinned> release-pr --dry-run` needs a token, so it probably can't, say so. Don't commit a token or call the GitHub API.
2. **`backend/uv.lock` in releases.** Add an `extra-files` entry so the release PR bumps the `tonewatch` package version inside `backend/uv.lock`, using release-please's `toml` updater with a jsonpath selecting the `[[package]]` whose `name == "tonewatch"`. Confirm the jsonpath syntax against the release-please docs for the pinned version, and add an assertion to the config unit test. If the toml updater can't select an array element by field, explain that and use the most robust supported alternative, e.g. a `generic` updater with an `x-release-please-version` marker is not possible in a generated lockfile. In that case, document why and keep the carryover item open.
3. **Trivy before publish in `release.yml`.**
   - Build the image, run Trivy with the **same** pinned Trivy action or container digest and flags `docker.yml` uses (HIGH,CRITICAL, `--ignore-unfixed`, exit code 1) against the exact image digest or loaded image, and only then push, sign and attest. A Trivy failure must stop the publish.
   - Keep `permissions` least-privilege per job, SHA-pinned actions (`just security` verifies pins), `timeout-minutes`, and `persist-credentials: false`.
   - Keep the `workflow_dispatch tag=` re-publish path working.
4. **Docs.** Update `docker/README.md` (or the release section of `CONTRIBUTING.md`) to cover:
   - release-please now opens one PR per component
   - publish is gated on Trivy
   - v0.2.0 was released without an image by decision

## Standing rules
- Never edit `docs/pm/**`.
- Never weaken a gate.
- Never create tags or releases, call the GitHub API, commit, or push.
- Don't bump unrelated action pins.

## Definition of done
- `just check` passes. Paste the tail.
- `just ci-local` with `TONEWATCH_E2E_PORT=8802` passes, including `just security` (action pins and zizmor on `release.yml`) and actionlint via pre-commit. If the Windows Playwright launcher hangs only in teardown after every spec passes, say so exactly.
- The report maps each item to its change and test. It states what can only be proven on GitHub: the next push to `main` opens a component release PR, and a merged release PR creates v0.3.0 and publishes after Trivy.
