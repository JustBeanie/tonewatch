# Brief: IC-E — make icad2mqtt CI green (vulnerable x/net, golangci-lint v2, container smoke)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Repo:** `JustBeanie/icad2mqtt` (Go, **public**). **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-ice`, branch `ic-e`, from `master` at `1fdac10`.

**Go environment:** use these exactly.
- `PATH` includes `C:\Program Files\Go\bin` (Go 1.27.0 is installed).
- `GOTOOLCHAIN=local`, `GOPROXY=off`, `GOFLAGS=-mod=mod`.
- `GOMODCACHE=C:\Users\beanie\AppData\Local\Temp\claude\C--Users-beanie-Documents-claude\84fbbdaf-f9a6-4447-a9f1-4fd699a53ece\scratchpad\gomod`. The PM pre-populated it; **read-only for you**, never delete from it.
- `GOCACHE` and `GOTMPDIR` go under the worktree's `.gocache\` (gitignored).
- **golangci-lint v2.13.2** is prebuilt at `C:\Users\beanie\AppData\Local\Temp\claude\C--Users-beanie-Documents-claude\84fbbdaf-f9a6-4447-a9f1-4fd699a53ece\scratchpad\gobin\golangci-lint.exe`.

**Hard rules:**
- Never write git state and never touch `.gocache/` in other worktrees.
- No binaries in the tree. No new modules beyond what's already in `go.mod`/`go.sum`.
- No real incident data. No local paths or internal jargon in tracked files.

## Why (PM evidence from GitHub CI run on `1fdac10`; `master` CI has been red since 2026-09-11)
1. **`vulnerability-scan` failed.** govulncheck: `Your code is affected by 7 vulnerabilities from 1 module`, namely `golang.org/x/net@v0.44.0`, reached through `internal/parse/parse.go:85` `html.Parse` on remote HTML.
   - **The PM already bumped it in this worktree:** `golang.org/x/net v0.59.0`, `go.mod` `go 1.26.0` (latest x/net requires it; Go 1.24 is out of support), `go mod tidy`.
   - With it, local `govulncheck ./...` gives `No vulnerabilities found`, and build, vet and test all pass. Keep that `go.mod`/`go.sum` diff exactly.
2. **`lint` failed.** golangci-lint v1.64.8 findings:
   - `internal/model/model_test.go:17` unchecked `json.Unmarshal` (errcheck)
   - `internal/fetch/fetch.go:50` unchecked `resp.Body.Close` (errcheck)
   - `internal/config/config.go:138` unused func `boolean`
   - `internal/publish/publish.go:58` unused field `lastPoll`
   - `internal/parse/parse.go:123` SA9003 empty branch

   Also, v1 can't lint a `go 1.26` module, so move to v2.
3. **The `docker` smoke failed.** `docker run --rm --read-only --cap-drop=ALL icad2mqtt:test --help` gave `exec: "--help": executable file not found in $PATH`. The Dockerfile uses `CMD ["./icad2mqtt"]`, and arguments to `docker run` replace `CMD`.

## Required
1. **Fix every lint finding properly.** Handle errors; for `resp.Body.Close` in a defer, check it or explicitly discard it with a justified comment. Delete dead code (`boolean`, `lastPoll`) only if it's truly unused, not by renaming. For the empty branch, fix the logic or remove it, and show it's behaviour-neutral with a test if logic changes. **No `//nolint`** unless you add a same-line justification for a real false positive.
2. **Migrate `.golangci.yml` to the v2 format** (`version: "2"`), keeping the same linters (bodyclose, errcheck, govet, ineffassign, staticcheck, unused) and not disabling any default checks.
   - `golangci-lint migrate` exists in v2 (you may use the prebuilt binary). Review the output; don't blindly accept exclusions.
   - Run the prebuilt v2.13.2 on `./...` until it reports **0 issues**.
3. **CI lint job:** `golangci/golangci-lint-action@ba0d7d2ec06a0ea1cb5fa41b2e4a3ab91d21278a # v9.3.0` (the PM dereferenced the annotated tag) with `version: v2.13.2`.
4. **Dockerfile:**
   - The builder is `golang:1.27-alpine` (the PM confirmed the tag exists), matching the `go 1.26.0` directive. Keep `--platform=$BUILDPLATFORM` and `TARGETOS`/`TARGETARCH`.
   - Replace `CMD ["./icad2mqtt"]` with `ENTRYPOINT ["/app/icad2mqtt"]`, so `docker run image --help` passes `--help` to the binary.
   - Confirm `--help` still returns before config loading and the privilege drop, so the `--cap-drop=ALL` smoke passes. Add a unit test for that ordering if one doesn't exist.
   - Check that the HA add-on still starts (add-ons run the image's entrypoint) and note it in the report.
5. `setup-go` keeps `go-version-file: go.mod`. Update any docs that state the Go version (`CONTRIBUTING.md`, README prerequisites).
6. Add a short "Unreleased" entry to `icad2mqtt/CHANGELOG.md` for the security update (x/net) and the Go toolchain bump. Keep the version at 2.0.0; nothing has been published yet.

## Evidence (the report is rejected without it)
- The `golangci-lint run ./...` output from the prebuilt v2.13.2: `0 issues`.
- A before/after table for each of the 5 findings, with file:line and the fix.
- `go test -cover ./...`, `go vet ./...`, `gofmt -l` on tracked and new `.go` files (empty), `GOOS=linux go vet ./...`, `GOOS=linux go build -o "$env:TEMP\icad2mqtt-linux" .`
- actionlint (prebuilt at `...\scratchpad\gobin\actionlint.exe`) on `.github/workflows/*.yml`: rc 0.
- `git diff --stat`, confirming `go.mod`/`go.sum` still carry the PM's bump.
- **Honesty rule:** paste output, never paraphrase a pass, and don't cite sources you didn't read.
