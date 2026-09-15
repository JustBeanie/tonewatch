# Brief: IC-C-fix — icad2mqtt publishing: public-repo hygiene, failure escalation, and the tests that actually assert the contract

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a2d2-153a-7ea0-9cdb-3325c294e07c`) · **Model:** gpt-5.6-luna, medium
**Repo:** `JustBeanie/icad2mqtt` (Go, **public**). **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-icc`, branch `ic-c`.
**Gates:**
- `go test ./...`, `go vet ./...`
- `gofmt -l $(git ls-files '*.go') internal` (empty)
- `icad2mqtt/`: `go vet` + `go build`

Same env as before: `GOMODCACHE` = `C:\Users\beanie\Documents\Proj\icad2mqtt-icb\.gocache\mod` (read-only), `GOFLAGS=-mod=mod`, `GOPROXY=off`, and local `.gocache/` for the rest.
**Git:** never write git state. **Never modify any `.gocache/`.**

## Verdict on IC-C: FAIL (public-repo hygiene, one bug, tests don't assert the contract)
**PM verified and kept:**
- `internal/publish`: topics `incidents` (retained), `incident` (not retained), `health` and `counts` (retained, counts only when discovery is on); canonical snapshot comparison excluding `fetched_at`.
- Discovery configs: `unique_id`, device, `state_class`, icons; empty retained clears when discovery is off.
- LWT `offline` + `online` on connect in `main.go`.
- Bounded, content-free log lines.
- Add-on kept raw-only with a warning; `docs/contract.md`.
- PM host run: all 8 packages pass (publish 90.8 %, main 60.2 %), vet clean, gofmt empty, add-on builds.

## Bugs / hygiene
1. **Internal jargon in a public repo.** "pending PM decision IC2 packaging consolidation" appears in `README.md:129`, `docs/contract.md:75`, `icad2mqtt/DOCS.md:7`, and the add-on log line `icad2mqtt/main.go:36`.
   - Replace everywhere with user-facing wording, e.g. *"The Home Assistant add-on currently publishes the raw topic only; structured topics and discovery require running the main icad2mqtt binary (for example the Docker image). Add-on support is planned."*
   - Afterwards, `grep -rniE '\bPM\b|brief|IC[0-9]|codex|engineer' --include='*' README.md docs icad2mqtt *.go internal` returns nothing (paste it).
2. **`justfile` hardcodes this machine's paths** (`C:\Users\beanie\...`, another worktree's module cache, PowerShell-only). That is non-portable and leaks local layout into a public repo.
   - Rewrite it portably: no absolute paths, use Go's default caches (users may override via env), `set windows-shell` only if needed.
   - Recipes: `check` (`go test ./...`, `go vet ./...`, gofmt check over `git ls-files '*.go'`, add-on vet and build) and `test-race` (documented as CI/Linux only).
   - Run it with **this** environment by setting the env vars in your shell before invoking `just`, not by baking them in. If `just` isn't installed here, say so.
3. **Page errors never escalate to `failing`.** `PageError` doesn't increment `ConsecutiveFailures`, so a permanent source layout change stays `degraded` forever.
   - Count page errors as consecutive failures; reset them on a valid page.
   - The status rules stay: `failing` at ≥ 3 consecutive failures of either kind, `degraded` for a partial page or a single failure, `ok` otherwise.
4. **Seeding and diff correctness are unproven.** `Valid` seeds with `engine.Diff(&s, &s)` and later calls `engine.Diff(nil, &s)`. `TestSeedNewUpdatedAndCounts` builds `n := s` and mutates `n.Incidents[0]`, which **also mutates `s`** (shared slice), so it can't distinguish right from wrong.
   - Deep-copy snapshots in tests (and in `Manager` if it retains any snapshot reference).
   - Confirm the engine's intended API: seed with `Diff(nil, first)` if that's the documented seed.
   - Fix `Valid` if needed.

## Tests (mandatory; the report maps each test name to a letter)
Replace or strengthen the current weak tests. `TestExamples` asserts nothing, `TestClosedAndNewEvents` only checks `len>0`, and `TestPollStructuredFixtureCycle` only checks `calls >= 4`.
- **A. Topic contract table:** for each publish kind (snapshot, event, health, counts, availability online/offline, discovery config, discovery clear, raw on, raw off), assert the exact topic, QoS 1, and the exact retained flag. Raw off gives no raw publish.
- **B. Suppression:**
  - The same page content with different `fetched_at` gives exactly 1 snapshot publish and 0 events.
  - A type change (independent deep copy) gives exactly 1 new snapshot publish and exactly 1 `updated` event for that id.
  - A cross-streets-only change gives 1 `updated` event.
- **C. Seeding and events with real fixtures** through `parse.Parse` → `normalize.Page` → `Manager.Valid`:
  - The first valid page (`events_all.html`) gives a retained snapshot and **0** events.
  - Then `events_type_changed.html` gives exactly one `updated` event.
  - Then a page with one row removed gives exactly one `closed` event with `status:"closed"`.
  - Then the same page again gives 0 events.
- **D. Page error:**
  - `events_missing_header.html` through the real `poll` path gives **no** publishes on `incidents`, `incident` or `counts`, and a health publish with `page_errors_total` +1.
  - Diff state is unchanged: the next valid page yields no spurious events.
  - Raw still publishes when enabled.
- **E. Health escalation:** 3 consecutive page errors give `failing`; a valid page gives `ok` (bug 3). Also mixed fetch failures and page errors reach `failing`.
- **F. Discovery privacy with fixtures:**
  - Serialize all discovery configs and the counts payload after polling `events_all.html`.
  - Assert none of the fixture's address or cross-street strings appear. Take the strings from the parsed snapshot, not hardcoded words.
  - Assert the exact key set of a config and the exact counts for that fixture.
- **G. LWT and online:**
  - `mqttOptions` sets the will topic `<base>/availability`, payload `offline`, QoS 1, retained.
  - Invoking `OnConnect` with a fake client publishes `online` retained to that topic.
- **H. Log privacy:** capture `log` output (`log.SetOutput` to a buffer) across polls of every `testdata/events_*.html` fixture, including a page error. Assert that no address, type or cross-street string from the parsed fixtures appears in the log.
- **I. End-to-end through `Run`:**
  - An `httptest` server serves `events_all.html` then `events_type_changed.html` as the original ISO-8859-1 bytes.
  - Use an injected sleep that stops after 2 polls and a fake MQTT publisher.
  - Assert the **ordered** publish sequence (topic and retained) and the decoded event JSON.
- **J.** Bug 1 grep (pasted) and a `justfile` with no absolute paths (`grep -n ':\\\\\|/c/Users\|C:\\\\' justfile` returns nothing).

## Evidence (the report is rejected without this)
- A table: test name → letter.
- For bugs 3 and 4: the failing test line first, the passing line, and a diff excerpt with file:line.
- `go test -cover ./...` (`internal/publish` ≥ 90 %, main ≥ 60 %), `go vet`, the gofmt command, and the add-on vet and build.
- One snapshot, event, health, counts and discovery config JSON printed **by an asserting test** (invented fixture values only).
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same check on `master` and pasting the result.

## Standing rules
- Never commit or push. No real incident data. No new modules. Don't weaken CI. Never touch `.gocache/`.
- Don't edit anything under `C:\Users\beanie\Documents\Proj\tonewatch`. Don't describe work you haven't done.
