# PM carry-over

Accepted gaps that must be written into a later brief. Remove an entry once that brief includes it. Resolved history lives in `docs/pm/reviews.csv` and the commit log.

## Open

- **Releases (user said "handle these", 2026-09-12).**
  - **Done:** PM enabled *Allow GitHub Actions to create and approve pull requests*, keeping the default token `read`. release-please reran green and opened PR #1 (v0.2.0).
  - 🚨 **Trap found before merging:** `release.yml / publish` triggered on `release: published`. release-please creates the release with `GITHUB_TOKEN`, and GitHub never starts workflows from `GITHUB_TOKEN` events, so the image would never publish. The PM fix (worktree `tonewatch-relfix`) chains `publish` on `needs.release-please.outputs.release_created`, and adds `workflow_dispatch` with a `tag` input for retries.
  - **Sequence:** land that fix, then merge PR #1, then watch `publish` (first real run: GHCR push, cosign, SBOM, provenance).
- 🛑 **GitHub Actions minutes exhausted (2026-09-12 13:33 UTC).** Every job fails with "recent account payments have failed or your spending limit needs to be increased". The user is aware; billing is the user's call (the PM never touches billing).
  - **Release:** v0.2.0 was merged (`e3397e6`), but its Release run never started. When minutes return, `gh run rerun 34696778462 --failed`: release-please creates v0.2.0 and `publish` runs in the same run.
  - **Usage this month:** 230 runs. Security 44 runs / ~608 wall-min (it ran on every push, docs-only PM commits included); CI 51 / 161; Docker 12 / 92.
  - **User chose the CI diet:**
    - skip docs-only pushes
    - `concurrency` cancel-in-progress
    - Security, ZAP/multi-arch, ARM and Windows run only when their code paths change, plus a weekly schedule
  - **At M9 landing:** apply the same path filters to its new `windows.yml`.
  - **While CI can't run:** local gates (`just check` / `security` / `e2e` / pre-commit) are the only verification, so run all of them before every push and record "CI pending (minutes)" in reviews.
  - **Release merge turned main red (found by `just ci-local` on the CI diet).** `test_version_is_defined` hardcoded `"0.1.0"`, and PR #1 bumped the version to 0.2.0. The fix asserts X.Y.Z matching the installed metadata; it lands with the CI diet.
    - **Lesson:** before merging a release PR, grep tests for the current version literal.
  - **Stale `uv.lock` after release:** release-please bumps `backend/pyproject.toml` to 0.2.0 but not `backend/uv.lock` (still `tonewatch 0.1.0`), so every `uv sync`/`uv run` rewrites the lock and dirties worktrees. The CI-diet commit carries a refreshed lock.
    - **Fix before the next release:** add `backend/uv.lock` to release-please `extra-files` (TOML jsonpath on the `tonewatch` package version), or run `uv lock` in the release PR.
  - **Flake, not regression:** `test_app_wiring.py` hit the 60 s faulthandler dump once under concurrent engineer load, then passed 3/3 standalone (41 s each). If it recurs, look at the retention loop's `os.stat` under slow IO.
  - **🛑 User: "for now lets only do local ci" (2026-09-12).**
    - **Actions off:** PM disabled every repo workflow with `gh workflow disable` (no file changes; re-enable with `gh workflow enable <id>` only when the user says so).
    - **CI diet:** landed anyway, so re-enabling is cheap.
    - **Verification:** `just ci-local` (pre-commit → check → security → api-drift → e2e) is the only gate, run by the PM before every push.
    - **Paused (Docker isn't installed on the PM host):** image build and 350 MB size budget, trivy, ZAP dast, container e2e/smoke, Linux and ARM pytest, and the release publish. Engineers' `PENDING-CI` items stay pending.
    - **Resuming:** when CI returns, re-enable the workflows, dispatch CI/Docker/Security on main, then rerun Release 34696778462 for v0.2.0.
- **State 2026-09-12 ~08:30.**
  - **Landed on main** (local `ci-local` green; Actions disabled):
    - `933807a` version test
    - `89b3795` looping file source fix
    - `f524529` CI diet
    - `897fa56` M9 Windows
    - `504d9b6` PM docs
  - **Workflows disabled:** new ones auto-enable, so `windows.yml` and `security-deps.yml` were disabled after landing (security-deps had two billing-failed runs).
  - **Running (luna high, 3 parallel; limits session 8% / weekly 6%):**
    - M13 in `tonewatch-m13`
    - M8.4-fix (resume `01a095b3…`) in `tonewatch-m84`: `__main__.py` rebase conflict + Content-Length 500/negative + private `_receive` + CRLF/missing-tolerance fixtures
    - M10a-rebase (resume `01a094ed…`) in `tonewatch-m10a`: conflicts in `__main__.py`, `alerts/mqtt.py`, `settings.py`, ASVS checklist
  - **Stash backups:** each rebased worktree keeps its `stash@{0}`, plus tar/diff backups in the PM scratchpad.
  - **Uncommitted PM files in main:** `briefs/M8.4-fix.md`, `reviews.csv` M8.4 row, ledger. Commit them with the next landing, never while a dispatcher might regenerate the ledger.
- **Codex limits (user request 2026-09-12).** `docs/pm/limits.py` reads session (5 h) and weekly (7 d) usage via the Codex app-server `account/rateLimits/read`. First reading: plus plan, session 7%, weekly 6%, weekly reset Sat 2026-09-19 02:08 MDT. The scheduling policy lives in PM memory (`tonewatch_delegate_to_engineers.md`).
  - **Until the dispatch.sh change:** run it before every dispatch and at every review.
  - **TODO when NO dispatch is running:** edit `docs/pm/dispatch.sh` to append a `limits.py` reading to the run log and report at start and end. Bash reads a running script incrementally, so never edit dispatch.sh while any dispatcher process is alive; check for `dispatch.sh` in the process list first.
- **User decisions 2026-09-12:**
  - **Merge release PR #1 (v0.2.0):** approved.
  - **Image visibility:** keep the GHCR package **PRIVATE until v1.0**, consistent with the private repo. Don't flip it. Revisit at M12.4 together with repo visibility.
  - **Consequences:** M10b's `image` resolution job stays red, and the add-on can't install from the store, until then.
  - **When flipping later:** it's irreversible (a public package can never go private) and UI-only (no REST endpoint; the PM `gh` token lacks `read:packages`).
- **M8.4 unblocked (2026-09-12).** The user's TTD install was found at `Desktop\Stuff\fire\TwoToneDetect73g\`. Its `tones.cfg` holds the user's email, so it's a gitignored private fixture only.
  - **Running:** brief `docs/pm/briefs/M8.4.md`, dispatched in worktree `tonewatch-m84`.
  - **At M8.4 landing:** remove the M8.4 BLOCKED line in PROGRESS.md.
- **M13 tone auto-discovery added to PLAN.md** (user request 2026-09-12), in parallel with M9/M10 and before M11.
  - **At M9 landing:** add M13.1–M13.7 checkboxes to PROGRESS.md (the M9 engineer is editing that file), and write + dispatch the M13 brief when an engineer slot frees up. Three engineers are running: M9, M10a, M8.4.

- **Image size margin is only about 2.8 MB** (CI run 34681525844, `e57ec0d`): 347,219,215 bytes against the 350 MB budget, after trimming venv tests, `__pycache__` and numpy headers in the builder stage.
  - The next runtime dependency will probably break the `size` job.
  - **Next lever, in the builder stage only:** `strip --strip-unneeded` on the `.so` files in site-packages (`av.libs`, `numpy.libs`), with the in-image import smoke as a guard. Deleting files in the runtime stage cannot shrink lower layers.
  - Put this in the S5, M9 or M10 brief, whichever adds dependencies first.
- ~~**M8 (Docker) — HTTPS in the image.**~~ Resolved: smoke verifies PyAV TLS against github.com inside the image (CI run 34681525844). History: The image's PyAV wheel must open **public** HTTPS with the product options (`tls_verify=1` + certifi `ca_file`). Linux wheels honour `ca_file` (CI run 34673148889), but the image may ship a different wheel. *In `docs/pm/briefs/M8.md`.*
- **M9 (Windows native).**
  - **MQTT selector thread:** `test_mqtt_real_broker_via_selector_thread` has an unconditional `@pytest.mark.skip`, so it runs on **no** platform, and the Windows selector-thread MQTT path has only a fake-client test. The M9 brief must require a real round-trip on windows-latest (amqtt in its own `SelectorEventLoop` thread, or a mosquitto binary) and remove the skip. The Linux real-broker test passes on ubuntu and ubuntu-arm.
  - **HTTPS:** Windows PyAV 18.1.0 does TLS through schannel, which **ignores `ca_file`** and uses the OS store. Public-CA feeds work. Document this.
  - **sounddevice / NumPy 2.5:** sounddevice 0.5.6 sets `ndarray.shape` in its cffi callback, which NumPy 2.5 deprecates. A future NumPy that removes the setter breaks the soundcard source at runtime. Re-verify on M9 and in the HIL checklist, and track the upstream fix.
- **M10 / M11 (HA consumers).** Alert payloads carry a **relative** `recording_url` (`/api/recordings/{id}`), which a webhook receiver, an HA entity attribute or a phone notification can't fetch.
  - Needs a `public_base_url` setting, or for the add-on the ingress URL / Supervisor-discovered host.
  - The M11 integration should resolve `media_content_id` through its authenticated proxy. Decide this in the M10 brief.
- **S6/S7 — remaining ASVS GAP rows.** S5 converted V3/V4 only, so 178 GAP rows remain. Convert them chapter by chapter on the gap-by-default rule; the PM reviews every positive row. Every positive row must carry a snippet that *proves* the control (S5 shipped a V3.4.2 snippet that was just a closing paren), and `fixed` means code changed in that milestone, otherwise use `pass`.
- **S5 follow-up — DAST.** First ZAP run (`d3643d5`) found REAL bugs, fixed by PM in `20d70e3`:
  - `POST /api/auth/login` returned 500 on non-JSON bodies
  - the SPA CSP lacked `form-action`/`base-uri`/`object-src`
  - Permissions-Policy/CORP/COOP/COEP headers were missing

  `rules.tsv` now IGNOREs 10049/10109/100000/100001 with justifications. 100000 is only safe because the `dast` job fails on any 5xx in the container log.
  - **Hollow gate:** `dast` went green on `20d70e3`, but the gate was hollow. `set +e` let `zap-baseline` exit 2 (WARN 10027, a minified-bundle false positive) pass. The follow-up re-enables `set -e` and IGNOREs 10027 with a justification.
  - **Confirmed** on `9b2e808` (Docker run 34687274921): `zap-baseline exit=0 zap-api-scan exit=0`, `5xx responses during scans: 0`, FAIL-NEW 0 / WARN-NEW 0 in both scans; CI and Security green; image 347,220,433 bytes. S5 is CI-complete; tick it `[x]` in `docs/PROGRESS.md` when M9 lands (the M9 engineer is editing that file).
  - **Watch:** COEP `require-corp` must not break the HA ingress iframe (HIL step for M10b).
  - **Review rule:** grep workflow `run:` blocks for `set +e` / `|| true`.
  - **Rule:** future scan findings are fixed in code first; an IGNORE needs a justification line.
- **Pin updates must never downgrade.** When re-pinning a floating `@vN` tag, pin the newest `vN.x.y` commit (S5 silently moved codeql-action 3.38.0 → 3.28.18 and setup-uv 6.8.0 → 6.4.3). The pin checker only runs online on the PM host and in CI (`security.yml / action-pins`); the sandbox run skips it.
- **Nit:** `storage/migrations/env.py` catches `AttributeError` as well as the context proxy's `NameError`; narrow it.
- **Later cleanup:** `types-pyyaml` is listed as a runtime dependency in `backend/pyproject.toml`; move it to dev dependencies.
- **Environment:**
  - The Codex sandbox user owns `.pytest-tmp/`, `backend/.pytest_cache`, `backend/backend/` and `%TEMP%\pytest-of-Beanie`. They are gitignored and harmless, but only that user can delete them.
  - The sandbox has no schannel credentials, so engineer TLS/HTTPS probes, `git ls-remote` and `curl` fail inside it. Verify TLS on the PM host or CI.
- **Leftover dirs:** `C:\Users\beanie\Documents\Proj\tonewatch-m7`, `tonewatch-s4`, `tonewatch-hotfix` and `tonewatch-hotfix2` still hold sandbox-owned files. Their git registrations and branches are gone, so the user can delete the folders manually.

## Standing rules for every brief (now also in `AGENTS.md`)

- Engineers never edit `docs/pm/**`. W1a-fix4 rewrote this file mid-run. Check `git status -- docs/pm` at every review.
- Never replace ignore files; extend them. Never reformat vendored or upstream files. Never weaken a gate, whether skips, hand-edited lockfiles or a widened CSP.
- Integration tests wait for **persisted** state with a bounded timeout. Update platform-skipped (`skipif sys.platform`) tests touching changed code. Tests never open real devices.
- Every CI job has `timeout-minutes`, and pytest enforces a 120 s per-test timeout with faulthandler.

## Update 2026-09-12 12:50: repo public, CI re-enabled
- Repo is PUBLIC as of 12:40, at the user's request. The GHCR package stays private until v1.0.
- The user re-enabled CI, which supersedes the local-only decision. Public repos get free standard runners. All 9 workflows are enabled.
- Dispatched on `bd9a200`: ci, security, security-deps, docker, windows. Security jobs pass, so there is no billing block.
- Keep `just ci-local` before PM landings.
- Rerun Release 34696778462 (v0.2.0) once CI is green. No tags exist yet.
- CI-diet triggers (paths filters, reduced push matrix) are kept for now. Revisit if full-matrix-on-push is wanted.
- M12.5 naming scrub is queued after M8.4, M10a and M13 land.

## Release-please: why v0.2.0 never tagged (found 2026-09-12 13:40)
- The Release workflow runs green on every push to main, but `publish` is skipped and there are no tags or releases.
- release-please v17.1.3 finds merged PR #1 ("chore: release main", label `autorelease: pending`, merge commit `e3397e6`). It then logs `PR component: undefined does not match configured component: backend` and builds 0 releases.
- `release-please-config.json` is unchanged since M8 (`component: backend`, `include-component-in-tag: false`, a single package). The PR title and body carry no component, so the merged PR never matches.
- **Next:** fix the config from the exact release-please source, so future release PRs match. Then either let release-please tag v0.2.0 from PR #1, or create tag v0.2.0 at `e3397e6` plus a GitHub release, relabel PR #1 `autorelease: tagged`, and dispatch Release with `tag=v0.2.0` to publish the (private) GHCR image. Do this only after Docker and Windows CI are green (M9-ci-fix).
- Also add `backend/uv.lock` to release-please extra-files (the stale-lock-after-bump issue).
