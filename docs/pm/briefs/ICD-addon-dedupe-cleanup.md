# Brief: IC-D — one Go module for Docker and the HA add-on; repository cleanup

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Repo:** `JustBeanie/icad2mqtt` (Go, **public**). **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-icd`, branch `ic-d` (created from `master` at `3b848a5`, which now contains IC-A, IC-B and IC-C).
**Go environment:**
- `PATH` includes `C:\Program Files\Go\bin`.
- `GOCACHE`/`GOPATH`/`GOTMPDIR` go under the worktree's `.gocache\` (gitignored).
- `GOMODCACHE=C:\Users\beanie\Documents\Proj\icad2mqtt-icb\.gocache\mod` (**read-only**), `GOFLAGS=-mod=mod`, `GOPROXY=off`.

**Hard rules:**
- Never write git state and never touch any `.gocache/`.
- Don't build binaries into the repo tree; use `-o "$env:TEMP\..."`.
- No new Go modules (the module cache is offline).
- No real incident data (addresses, types, times) in code, tests, docs or logs.
- No local paths (`C:\Users\...`) and no internal project jargon in any tracked file.

## Background
The user approved removing the add-on's duplicate module. `icad2mqtt/` (the HA add-on folder) has its own `go.mod`, `go.sum` and a 170-line `main.go` that predates the structured publisher. So the add-on still publishes only the old raw payload, and the repo maintains two copies.

HA Supervisor builds a local add-on with the **add-on folder as the Docker build context**, so that folder can't `COPY` the root module. The standard fix is a prebuilt image referenced by `image:` in the add-on `config.yaml`.

## Required
1. **One binary reads add-on options natively.**
   - In `internal/config`, when `/data/options.json` exists (make the path injectable for tests), load options from it: `mqtt_broker`, `mqtt_base_topic`, `mqtt_topic`, `publish_raw`, `ha_discovery`, `mqtt_username`, `mqtt_password`, `poll_interval`.
   - It must have exactly the same defaults and null handling as today's `run.sh`: a missing or `null` key means the default, and an explicit `false`/`0` is kept.
   - Environment variables still work for plain Docker.
   - Precedence must be documented and tested: if both are set, **options.json wins in add-on mode**.
   - Validation errors must never echo the password.
2. **Delete** `icad2mqtt/go.mod`, `icad2mqtt/go.sum`, `icad2mqtt/main.go`, `icad2mqtt/run.sh`, `icad2mqtt/run_test.sh` and the add-on `Dockerfile`/`build.yaml`.
   - Port every `run_test.sh` jq case into Go table tests for the options loader, including explicit `false`/`0` and `{}`.
3. **Root `Dockerfile`** (one image for Docker and the add-on):
   - Use the Go toolchain version from `go.mod`, a current pinned Alpine 3.x base (check which exists; don't guess a future version), non-root user and `ca-certificates`.
   - It needs no `jq` or bash.
   - Multi-arch buildable for `linux/amd64` and `linux/arm64` (use `TARGETOS`/`TARGETARCH` with `CGO_ENABLED=0`).
   - The add-on must be able to read `/data/options.json` as that user. Check whether HA mounts `/data` readable by a non-root user; if unsure, document the finding and choose safely, stating the trade-off.
4. **Add-on `icad2mqtt/config.yaml`:**
   - Add `image: ghcr.io/justbeanie/icad2mqtt` (a multi-arch manifest).
   - Set `version: "2.0.0"`.
   - `arch: [aarch64, amd64]`: HA has deprecated 32-bit arches; note this in the changelog.
   - Keep `options`/`schema` compatible.
   - Add `icad2mqtt/CHANGELOG.md` with a 2.0.0 entry: structured topics, availability, health, discovery counts, the single image and the dropped arches.
   - Keep `DOCS.md` accurate.
5. **CI (`.github/workflows/ci.yml`):**
   - Remove the separate add-on module job.
   - Keep the root gates: gofmt, vet, build, `test -race`, mod verify.
   - The Docker job builds multi-arch without pushing on PRs and pushes to `master`.
   - Pin every action by full SHA with a version comment, reusing SHAs already present where possible.
6. **Add `.github/workflows/release.yml`.**
   - Trigger **only** on tags matching `v*.*.*`, plus `workflow_dispatch` with a `tag` input.
   - Validate the tag regex and that it equals `v` + the `icad2mqtt/config.yaml` version, failing otherwise.
   - buildx `linux/amd64,linux/arm64`, then push `ghcr.io/justbeanie/icad2mqtt:<version>` and `:latest`, with `provenance: true` and `sbom: true`.
   - Permissions: `contents: read`, `packages: write` on that job only.
   - Pass the tag via `env:`, never `${{ }}` inside `run:`.
   - **Don't** run it; the PM will ask the user before the first tag.
7. **Repository cleanup:**
   - Delete `GITHUB_SETUP.md` (a stale one-time setup guide).
   - Move `SECURITY_AUDIT.md` to `docs/security-audit.md` and update it for the new architecture (single image, options loader, the release workflow's least-privilege setup). Keep it honest; don't invent audits.
   - `docker-compose.yml`: remove the obsolete `version:` key, pin `eclipse-mosquitto` to a specific version tag (check the actual latest 2.x tag; don't guess), and use the current env names (`MQTT_BASE_TOPIC`, `PUBLISH_RAW`, `HA_DISCOVERY`).
   - `.dockerignore`: keep `testdata`, docs and tests out of the image context where safe, but don't break `go build`.
   - `.gitignore`: remove the duplicated `.gocache/` and `.DS_Store` lines.
   - `justfile`: drop the add-on module step.
   - README: update Project Structure, Docker and Add-on sections, and link `docs/contract.md`. Remove anything describing the old two-module layout. Keep it concise.
   - Fix anything else stale you find, and list each item in the report.

## Mandatory tests
- **A. Options loader table:** `{}` gives all defaults; `publish_raw:false` stays false; `poll_interval:0` stays 0 and then is rejected by the existing validation exactly as today (state which); `null` values give defaults; a malformed JSON error doesn't contain the password string.
- **B. Precedence:** env set plus an options.json present gives the options values; no file gives env.
- **C.** `main` wiring uses the loader. Show it with a test that points the loader path at a temp options file and asserts the resulting `Config` (redacted `String()`).

## Evidence (the report is rejected without it)
- A table mapping test name → letter, with each test's first-run result and its passing line.
- `go test -cover ./...`, `go vet ./...`, `gofmt -l $(git ls-files '*.go')` (empty), and `go build -o "$env:TEMP\icad2mqtt.exe" .`.
- If Docker is available, `docker build` output. If not, say so; don't claim it.
- `git status --short`, plus a list of every deleted and moved file.
- Grep proof: `rg -n "C:\\\\Users|/c/Users|\bbrief\b|codex" --hidden -g '!.git' -g '!.gocache'` returns nothing.
- **Honesty rule:** never claim a check passed without pasting it, and never cite a source you didn't read.
