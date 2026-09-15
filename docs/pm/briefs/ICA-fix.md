# Brief: IC-A-fix — icad2mqtt foundation: add-on bool bug, real jitter with a 60 s floor, secret-safe config, tests

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a2bd-dc79-7682-bc0f-bfdffb0a8db2`) · **Model:** gpt-5.6-luna, medium
**Repo:** `JustBeanie/icad2mqtt` (Go). **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-ica`, branch `ic-a`.
**Gates:** `go test ./...`, `go vet ./...`, `gofmt -l $(git ls-files '*.go') internal` (empty), and in `icad2mqtt/`: `go vet ./...` + `go build`. Go 1.27.0 is at `C:\Program Files\Go\bin`; use the same `.gocache/` variables.
**Git:** never write git state. Read-only diff/show is fine.
**🚨 Never modify anything under `.gocache/`** (in particular `.gocache/mod`, the verified module cache). Your last run tried to rewrite dependency files there to satisfy a literal `gofmt -l .`. That is tampering with third-party sources: never do it again, and report tool limitations instead.

## Verdict on IC-A: FAIL (bugs + tests + evidence)
**PM verified and kept:**
- `internal/config`: defaults, 60 s clamp, `HTTP_TIMEOUT` 5–60, strict booleans, `+`/`#` topic validation.
- `internal/fetch`:
  - 200-only; 5 MiB reject via `LimitReader`+1
  - ISO-8859-1 decode by byte → rune; SHA-256; `Date` parse
  - bounded errors, with no body in the error
- `time/tzdata` in main.
- Username and password passed to the paho options.
- `PUBLISH_RAW=false` skips raw publishing.
- The add-on schema adds `password?`; README updated.
- `govulncheck` was already in CI and is kept.
- PM host run: `go test` passes; `go vet` is clean; `gofmt` on project files is empty; the add-on copy vets and builds; `go mod verify` reports all modules verified.

## Bugs
1. **The add-on can never turn raw publishing off.**
   - **Cause:** `icad2mqtt/run.sh` uses `jq -r '.publish_raw // true'`. jq's `//` replaces **false** as well as null, so `publish_raw: false` exports `true`.
   - **Fix:** use `jq -r 'if .publish_raw == null then true else .publish_raw end'`, and apply the same null-only pattern to **every** boolean or number option (`ha_discovery`, `poll_interval`).
   - **Test:** add `icad2mqtt/run_test.sh` (POSIX sh, runnable on CI Linux) that feeds `options.json` variants to the jq expressions and asserts the exported values for `true`, `false` and absent. Wire it into CI only if CI already has a shell-test pattern; otherwise document the command. Also run it on this host with Git Bash plus a `jq` if available, or say that it isn't available.
2. **No jitter in production, and a 0 s retry is possible.**
   - `main.go` builds `fetch.Fetcher` without `Rand`, so `BackoffDelay` always returns `max/2` (no jitter).
   - With `Rand`, full jitter can return **0**, which re-polls immediately and violates the binding **60 s polling floor**.
   - **Fix:**
     - Default `Rand` to `math/rand/v2` when nil (stdlib).
     - Define the delay as `PollInterval + rand[0, span)`, where `span = min(10m, PollInterval·2^(failures)) − PollInterval`. The delay is never below `PollInterval` and never above 10 min.
     - Document the formula in `doc.go`.
   - **Tests:**
     - The nil `Rand` path yields values in range over many samples, and not all equal.
     - The injected `Rand` bounds are exact: min equals `PollInterval`, max is just below the cap, and the cap holds at 10+ failures.
     - Failures reset to 0 after a success; test through `Fetch` against `httptest` fail → fail → success.
3. **Config can leak the password.** `config.Config` has an exported `MqttPassword`, and any `log.Printf("%+v", cfg)` prints it.
   - **Fix:** add `func (c Config) String() string` (and `GoString`) that redacts the password, and the username if present in the broker URL. Use `redactBroker` for the broker.
   - **Test:** `fmt.Sprintf("%v %+v %#v", c, c, c)` contains no secret.
4. **The add-on duplicate has no backoff.** `icad2mqtt/main.go` mirrors the config but not the backoff or jitter. Mirror bug 2's behaviour there, keeping it minimal. Don't restructure the duplication (PM decision pending), and list the exact mirrored functions in the report.
5. **Stray build artifact.** Delete `icad2mqtt/icad2mqtt.exe`, a 10 MB local build output. It's gitignored, but never leave binaries in the add-on build context.

## Tests (mandatory; map test name to letter)
- **A.** Clamp warning: capture `log` output (`log.SetOutput` to a buffer, restored after) and assert exactly one warning for `POLL_INTERVAL=30` and none for 60.
- **B.** Config table-driven: each env var's default, a valid override, and an invalid value.
  - `MQTT_TOPIC` empty, derived from base.
  - `HTTP_TIMEOUT` 4/5/60/61.
  - `PUBLISH_RAW`/`HA_DISCOVERY` accept `true`/`false` and reject `TRUE`/`1`/`yes`.
  - Topic cases: `a/+/b`, `#`, `""`, and spaces-only.
- **C.** Bug 3 redaction test.
- **D.** Bug 2 tests, including reset on success through `Fetch`.
- **E.** `Run` loop: make the sleep/timer injectable (e.g. a `sleep func(ctx, d) bool` field), then assert:
  - after a failed poll, the requested delay comes from `BackoffDelay()` and is ≥ `PollInterval`
  - after a success, the delay equals `PollInterval`
  - context cancel exits promptly
- **F.** MQTT options: extract `mqttOptions(c Config) *mqtt.ClientOptions` and assert username and password are set only when non-empty, plus client id and broker.
- **G.** Bug 1 `run_test.sh`.
- **H.** Fetch: a non-200 error contains no body (exists); a `Date` header that's missing or invalid gives a zero time and no error; a request-creation error on a bad URL is counted as a failure.
- Coverage targets: `internal/config` ≥ 90 %, `internal/fetch` ≥ 90 %, main package ≥ 60 %.

## Evidence (the report is rejected without this)
- A table: test name → letter.
- Per bug: the failing test line first, the passing line, and a diff excerpt with file:line.
- `go test -cover ./...`, `go vet ./...`, the gofmt command above (empty), and the add-on `go vet` + `go build` output.
- The config table (env var | default | validation | add-on option) and the backoff formula with a test excerpt.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same check on `origin/master` and pasting the result.

## Standing rules
- Never commit or push. No real incident data. No new modules (`math/rand/v2` is stdlib).
- Don't touch IC-B packages (`internal/{parse,normalize,model,diff}`), which aren't in your branch.
- Never weaken CI, and never edit `.gocache/`. Don't edit anything under `C:\Users\beanie\Documents\Proj\tonewatch`.
- Don't describe work you haven't done.
