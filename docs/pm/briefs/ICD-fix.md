# Brief: IC-D-fix — restore the removed CI gates, no publishing from CI, arm64 build emulation, drop root instead of DAC_READ_SEARCH

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0ac91-3b7a-7653-841e-7c8c3ff53e96`) · **Model:** gpt-5.6-luna, medium
**Repo and work dir:** as IC-D (`icad2mqtt-icd`, branch `ic-d`). The Go environment and hard rules are unchanged: never write git state, never touch `.gocache/`, no new modules, and no binaries in the tree.

## Verdict on IC-D: FAIL
**PM verified and kept:**
- The options loader: pointer-based null handling, defaults matching the old `run.sh`, explicit `false`/`0` kept, and `0` rejected by the existing positive-integer validation, as before. Options win over env when the file exists, and the malformed-JSON error omits the password.
- The duplicate add-on module, scripts and Dockerfile are removed, and the run_test.sh cases are ported to Go.
- `GITHUB_SETUP.md` is deleted and the audit moved to `docs/security-audit.md`.
- Compose is updated, with `eclipse-mosquitto:2.1.2-alpine` and `alpine:3.24.1` (both tags confirmed on Docker Hub by the PM).
- Add-on `config.yaml` v2.0.0 with `image:`, and the changelog.

**Why it fails:**
1. **CI gates were deleted without being asked.** `master`'s `ci.yml` had a `golangci-lint` job (v1.64.8), `govulncheck`, a Docker image **Trivy scan** (`exit-code: 1`, `ignore-unfixed`) and a container smoke (`docker run --rm --read-only --cap-drop=ALL icad2mqtt:test --help`). All of them are gone. That's a gate weakening. Restore every one, pinned by full SHA with version comments, and look up the SHA for each tag. Keep the coverage artifact upload too.
2. **CI publishes a public image on every push to `master`** (`ghcr.io/justbeanie/icad2mqtt:master`). The PM's IC-D brief wrongly said "push on master", and that's corrected here. Creating a public GHCR package needs the user's explicit approval. **Remove every push and `packages: write` from `ci.yml`.** CI builds only, and **only** `release.yml` publishes (on a tag the user approves).
3. **The arm64 image can't build.** The final stage runs `apk add` for `linux/arm64`, which needs emulation, but neither workflow sets up QEMU. Add `docker/setup-qemu-action` (the tonewatch repo uses `@29109295f81e9208d7d86ff1c6c12d2833863392 # v3.6.0`) before buildx, in both `ci.yml` and `release.yml`. Don't drop arm64.
4. **Replace `privileged: [DAC_READ_SEARCH]`.** That capability lets the process read any file in the container regardless of permissions, and it lowers the add-on's security rating.
   - Instead the image starts as root (remove `USER appuser` from the Dockerfile). The binary loads config (including `/data/options.json`), **then** permanently drops to the unprivileged `appuser` uid/gid with `syscall.Setgroups([]int{})`, `Setgid`, `Setuid`, all on Linux only. That happens before any network I/O.
   - If it started as root and the drop fails, exit non-zero. If it's already non-root (Docker `user:`), skip the drop.
   - Look the uid/gid up from `/etc/passwd` by name, or bake fixed ids into the Dockerfile (`adduser -u 10001`) and use constants. Pick one and justify it.
   - Put the Linux code in a `_linux.go` file with a no-op on other platforms. Make the drop function injectable, and test the ordering: config is loaded before the drop, the drop happens before any fetch/MQTT, and a failure exits.
   - Remove `privileged` from `config.yaml`, and update `DOCS.md` and `docs/security-audit.md` accordingly.
   - Add `user: "10001:10001"` (or your chosen ids) to the compose example as a hardening option, and document it.
5. **Harden `release.yml`:**
   - Add top-level `permissions: {}`, with `contents: read` and `packages: write` on the job only.
   - Set checkout `persist-credentials: false`.
   - Add QEMU.
   - Run a Trivy scan of the amd64 image **before** pushing (build with `--load` for amd64, scan, then do the multi-arch push).
6. **`.gitignore`** still has `.gocache/` twice; remove the duplicate.
7. **Tests weren't written first:** every test "passed on first run". For the new privilege-drop tests, show each failing before the implementation.

## Evidence (the report is rejected without it)
- `git diff master -- .github/workflows/ci.yml`, showing every original gate is present (lint, govulncheck, race tests plus coverage artifact, docker build, Trivy, `--help` smoke) and no push anywhere.
- `rg -n -- "--push|packages: write|docker login|type=registry" .github/workflows/ci.yml` returns nothing (the `on: push:` trigger is fine).
- actionlint on both workflows. If it isn't available, the PM has a copy at `C:\Users\beanie\AppData\Local\Temp\claude\C--Users-beanie-Documents-claude\84fbbdaf-f9a6-4447-a9f1-4fd699a53ece\scratchpad\gobin\actionlint.exe`. Paste the output. Note that a `$/...` self-repository `uses:` is **not** needed here.
- A table mapping each privilege-drop test to its first failing line and its passing line.
- `go test -cover ./...`, `go vet ./...`, gofmt (empty), `GOOS=linux go vet ./...` and `GOOS=linux go build -o "$env:TEMP\icad2mqtt-linux" .` (proves the `_linux.go` path compiles).
- **Honesty rule:** don't claim anything you didn't run, and don't cite anything you didn't read.
