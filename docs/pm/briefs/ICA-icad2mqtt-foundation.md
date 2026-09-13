# Brief: IC-A — icad2mqtt foundation (config, fetch, timezone data, CI)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium
**Repo:** **`JustBeanie/icad2mqtt`** (Go), NOT ToneWatch. **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-ica`, branch `ic-a` (from `origin/master`).
**Gates** (they replace the dispatcher's `just check`):
- `go test ./...`
- `go vet ./...`
- `gofmt -l .` with empty output
- `golangci-lint run`, if it's installed

`-race` needs cgo and a C compiler, which this Windows host lacks, so race tests run only in GitHub CI (Linux). Say this in the report; don't disable race anywhere.
**Go caches:** set `GOCACHE`, `GOMODCACHE`, `GOPATH` and `GOTMPDIR` to directories under `.gocache/` in the work dir, and add `.gocache/` to `.gitignore`.
**Go toolchain:** Go 1.27.0 is installed at `C:\Program Files\Go\bin\go.exe`. Prepend that directory to PATH in every shell, because your environment may predate the install. The PM pre-downloaded the module cache into `.gocache/` using exactly those variables, so builds work offline.

## Context
- Read the reviewed plan first: `C:\Users\beanie\Documents\Proj\tonewatch\docs\pm\reports\M17-icad2mqtt-plan-20260912-234423.md` (sections 1, 6, 7, 8; tasks IC3, IC4, IC12).
- Also read the PM's verified page facts in `C:\Users\beanie\Documents\Proj\tonewatch\docs\pm\carryover.md`, section "M14–M18 kickoff":
  - The server sends **no** ETag, Last-Modified or Cache-Control, so there are no conditional requests. Change detection stays content-hash based.
  - The charset is ISO-8859-1.
- **In parallel,** another engineer (IC-B) adds new packages `internal/parse`, `internal/normalize`, `internal/model` and `internal/diff`. **Don't create or touch those.** A later task (IC-C) wires everything into publishing. Keep `main.go` edits focused on config and fetch.

## User decisions (binding)
- Raw HTML publishing stays **on** by default (`PUBLISH_RAW=true`).
- HA MQTT discovery is **opt-in** (`HA_DISCOVERY=false` by default). IC-A only adds the config flag.
- Polling has a floor of **60 s**.

## Required
1. **Config (`internal/config`, test-first).** Move env parsing out of `main.go`:
   - Existing: `MQTT_BROKER`, `MQTT_TOPIC` (the raw topic), `CLIENT_ID`, `POLL_INTERVAL`, `HTTP_USER_AGENT`.
   - New: `MQTT_BASE_TOPIC` (default `911/cad`), `PUBLISH_RAW` (default true), `HA_DISCOVERY` (default false), `MQTT_USERNAME`, `MQTT_PASSWORD` (optional; never logged or printed, and redacted in any config dump), `HTTP_TIMEOUT` (default 15 s, 5–60).
   - **`POLL_INTERVAL` default becomes 60.** A configured value below 60 is **clamped to 60 with one warning log**, not rejected, so existing add-on installs set to 30 keep starting.
   - Topics must be valid MQTT publish topics (no `+`/`#`, not empty); booleans parse strictly.
   - Update `icad2mqtt/config.yaml` (options + schema: `mqtt_base_topic`, `publish_raw`, `ha_discovery`, `mqtt_username`, `mqtt_password` as `password?`) and `icad2mqtt/run.sh` to export them. Keep the add-on schema valid.
   - Also keep the add-on's own copy of the code building. Document in the report exactly what you had to mirror, but **don't delete or restructure the duplicated add-on source.** The HA Supervisor builds add-ons with the add-on folder as build context; the PM decides the fix after this task.
2. **Fetch layer (`internal/fetch`, test-first, using `httptest`).**
   - GET with the User-Agent, timeout, and a 5 MiB cap (reject if over, not truncate).
   - Only 200 counts as success. Decode ISO-8859-1 to UTF-8 **without new dependencies** (each byte maps to the same code point).
   - Return body plus a SHA-256 content hash and the response `Date`.
   - **Backoff on consecutive failures:** exponential with full jitter, base = poll interval, cap 10 min. Reset on success. Inject clock and random source for tests.
   - Errors are bounded strings: never include the body, and never log page contents.
3. **Timezone data.** `import _ "time/tzdata"` in the main package, with a comment on why (scratch/non-root images have no zoneinfo). Add a test that `time.LoadLocation("America/New_York")` works.
4. **Main loop.** Use the new config and fetch. Raw publishing behaves exactly as today when `PUBLISH_RAW=true` (topic, QoS 1, not retained, publish on change); when false, nothing goes to the raw topic. Apply backoff between failed polls. Add the MQTT username/password to the client options when set.
5. **CI (`.github/workflows/ci.yml`).** Keep every existing gate. Add `govulncheck ./...` if it isn't already present, pinned the same way other tools are (SHA-pinned actions or a fixed tool version). Don't weaken or remove anything, and don't change base images.
6. **Docs.** README configuration table (all env vars, defaults, the clamp behaviour, the password never logged) and the add-on options.

## Standing rules
- Never commit or push. The PM reviews and asks the user before any push to this public repo.
- No real incident data anywhere: commits, tests, logs or docs.
- New dependencies: none.
- Never weaken CI (`.github/workflows/ci.yml`, `.golangci.yml`), and never delete files the brief didn't ask you to touch.
- Don't edit anything under `C:\Users\beanie\Documents\Proj\tonewatch`.

## Definition of done
- `go test ./...`, `go vet ./...` and `gofmt -l .` all pass; paste the output. Include `golangci-lint run` output if installed, or say it isn't.
- The final report lists every changed file, the config table, the backoff formula with a test excerpt, the add-on duplication findings, and anything you couldn't verify locally (race).
