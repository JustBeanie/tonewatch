# Brief: IC-F — minimal runtime image so the Trivy gate passes

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0acda-a5a5-71f2-a730-8918216415b1`) · **Model:** gpt-5.6-luna, medium
**Repo:** `JustBeanie/icad2mqtt` (public). **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-ice`. The PM committed and pushed IC-E as `d5c0828`, so the worktree is clean at `master`. Keep branch `ic-e`.
**Go environment:** same as IC-E (`GOTOOLCHAIN=local`, `GOPROXY=off`, `GOFLAGS=-mod=mod`, and the read-only scratchpad `GOMODCACHE`, prebuilt golangci-lint v2.13.2 and actionlint).
**Hard rules:** as in IC-E. Never write git state.

## Why (GitHub CI on `d5c0828`, run 35168975234)
- `test`, `lint` and `vulnerability-scan` now **pass**. In `docker`, **Build** and the **`--help` smoke pass**, but **Scan Docker image** fails.
- Trivy found 20 vulnerabilities in the **Alpine 3.24.1 OS packages `libcrypto3` / `libssl3`** (OpenSSL 3.5.7-r0, fixed in 3.5.8-r0), including 2 HIGH. The Go binary target (`app/icad2mqtt`) has **0**.
- The bridge is a static `CGO_ENABLED=0` Go binary that uses Go's TLS, not OpenSSL. The runtime only needs the binary and a CA bundle.

## Required
1. **Change the Dockerfile runtime stage to `FROM scratch`.**
   - In the builder stage, install `ca-certificates` (and `tzdata` only if the binary needs system zoneinfo; check whether IC-A embeds `time/tzdata`). Copy `/etc/ssl/certs/ca-certificates.crt` into the runtime image.
   - Copy the binary to `/app/icad2mqtt` and keep `ENTRYPOINT ["/app/icad2mqtt"]` and `ENV GODEBUG=netdns=go`.
   - No shell, no package manager, no `adduser`. The privilege drop already uses numeric UID/GID 10001 constants and needs no `/etc/passwd`.
   - Check whether anything in the code or tests assumes `/etc/passwd`, a shell or `/tmp`. If it needs a writable temp dir, fix that (the container smoke runs `--read-only`).
2. **Keep the multi-arch build (`linux/amd64`, `linux/arm64`) working.** With no `RUN` in the final stage, QEMU is no longer needed for it. Keep the QEMU steps anyway: they're harmless, and a future stage may need them.
3. **Update `docs/security-audit.md`, `icad2mqtt/DOCS.md` and the README** wherever they say "Alpine" or describe the runtime base. Add a line to the `icad2mqtt/CHANGELOG.md` "Unreleased" section.
4. **Don't touch the Trivy gate settings** (`exit-code: 1`, `ignore-unfixed: true`). Don't add a `.trivyignore`.
5. **A Go test** asserting the CA bundle path is what the HTTP client relies on isn't needed. Instead, add a short comment in the Dockerfile explaining why `scratch` is safe: static binary, Go TLS, CA bundle copied.

## Evidence (the report is rejected without it)
- The full new Dockerfile.
- `go test ./...`, `go vet ./...`, gofmt empty, `GOOS=linux go build`, `golangci-lint run ./...` (0 issues), and actionlint rc 0.
- A statement of whether `time/tzdata` is embedded, with the grep that proves it.
- Docker isn't installed on this machine. Say so; don't claim a local image build. The PM verifies through CI.
- **Honesty rule:** paste output; don't cite sources you didn't read.
