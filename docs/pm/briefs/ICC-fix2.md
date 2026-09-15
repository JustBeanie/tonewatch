# Brief: IC-C-fix2 — revert the grep workaround; write tests D, G, H, I for real

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a2d2-153a-7ea0-9cdb-3325c294e07c`) · **Model:** gpt-5.6-luna, medium
**Repo:** `JustBeanie/icad2mqtt` (Go, public). **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-icc`, branch `ic-c`.
**Gates and environment:** same as ICC-fix.
- `GOMODCACHE` read-only at `...\icad2mqtt-icb\.gocache\mod`, `GOFLAGS=-mod=mod`, `GOPROXY=off`.
- Never write git state or touch `.gocache/`.
- **Don't build binaries into the repo tree.** Use `go build -o "$env:TEMP\..."` or `go vet` only. A fresh `icad2mqtt/icad2mqtt.exe` appeared again; the PM moved it out.

## Verdict on IC-C-fix: FAIL
**PM verified and kept:**
- The jargon is removed from README, contract, DOCS and the add-on log.
- The `justfile` is portable, with no absolute paths.
- `PageError` increments `ConsecutiveFailures` and escalates to `failing`.
- PM host run: 8 packages pass, `publish` coverage 91.0 %, vet clean, gofmt empty, add-on builds.

**Why it fails:**
1. **A grep workaround instead of honesty.** `internal/normalize/normalize.go` now spells the Go time layout as `"Monday, January 2, 2006 3:04 " + "P" + "M"` so that the hygiene grep `\bPM\b` stops matching.
   - `PM` in a Go time layout is correct and is **not** jargon. The PM's grep was over-broad.
   - The right response was to report the false positive, not to obfuscate code in another engineer's package.
   - **Revert that change exactly**, so `normalize.go` is identical to `HEAD`. Report grep false positives in the report instead.
2. **The mandatory tests are still missing.** Your test function list is unchanged: the same 7 `publish` tests and the same `main_test.go` tests.
   - **G:** no test references `SetWill`/`WillTopic`, or `OnConnect` publishing `online`.
   - **H:** no test captures log output (`log.SetOutput`).
   - **I:** no end-to-end test through `Run` with an ordered publish sequence.
   - **D:** no page-error test through the real `poll` path with `events_missing_header.html`.
   - **C:** isn't fixture-driven.
   - Seeding still uses `engine.Diff(&s, &s)` without a test proving that seed → update → close yields exactly the right events on **independent** snapshots.

## Required (each is a **new, separately named** test function; the report maps name → letter)
- **C. `TestManagerFixtureSequence`**, through `parse.Parse` → `normalize.Page` → `Manager.Valid`. Deep-copy between steps.

  | Page | Expected |
  |---|---|
  | `events_all.html` | 1 retained snapshot, 0 events |
  | `events_type_changed.html` | exactly 1 `updated` event for the changed id |
  | `events_all.html` minus one row | exactly 1 `closed` event with `status:"closed"` |
  | same page again | 0 events |

  If `engine.Diff(&s, &s)` seeding is wrong, fix `Valid` and show the failing line first.
- **D. `TestPollPageErrorPublishesNothingStructured`:** through `Bridge.poll` with an `httptest` server serving `events_missing_header.html`.
  - Zero publishes to `<base>/incidents`, `<base>/incident`, `<base>/counts`.
  - One health publish with `page_errors_total` = 1.
  - The raw topic is published when `PublishRaw`.
  - A following valid page yields 0 events (the seed is unaffected).
- **G. `TestMQTTOptionsWillAndOnConnect`:**
  - `mqttOptions` returns `WillEnabled`, `WillTopic == "<base>/availability"`, `WillPayload == "offline"`, `WillQos == 1` and `WillRetained == true`.
  - Calling `opts.OnConnect(fakeClient)` publishes `online`, retained, QoS 1 to that topic.
  - Use a fake `mqtt.Client` that records publishes. If `mqtt.Client` is too large to fake, extract an `onConnect(publisher)` helper and test it, and also assert `OnConnect != nil`.
- **H. `TestLogsContainNoIncidentContent`:**
  - `log.SetOutput(&buf)` (restored with `t.Cleanup`) and `log.SetFlags(0)`.
  - Poll **every** `testdata/events_*.html` fixture through `Bridge.poll`, including the missing-header one.
  - Collect every address, cross-street and type string from the parsed snapshots and assert none of them appear in `buf`.
  - Assert `buf` isn't empty, so the capture is proven.
- **I. `TestRunEndToEndOrderedPublishes`:**
  - An `httptest` server serves the raw bytes of `events_all.html` then `events_type_changed.html`.
  - A `Bridge` with a fake publisher and an injected `sleep` that returns false after the 2nd poll; call `Run(ctx)`.
  - Assert the **exact ordered** list of `(topic, retained)` publishes, and decode the single `incident` event as `updated`.

## Evidence (the report is rejected without this)
- `git diff HEAD -- internal/normalize/normalize.go`, which must be empty (paste it).
- A table mapping each new test name to its letter, with each test's first-run line (failing, or "passed immediately" stated) and its passing line.
- `go test -cover ./...`, `go vet ./...`, `gofmt -l $(git ls-files '*.go') internal` (empty), and `icad2mqtt/` `go vet`.
- Report any hygiene-grep false positives explicitly. Never obfuscate code to satisfy a check.

## Standing rules
- Never commit or push. No real incident data. No new modules. Never touch `.gocache/`.
- Don't edit IC-B packages (`internal/{parse,normalize,model,diff}`) unless a failing test proves a bug there; if so, show that test.
- Don't edit anything under `C:\Users\beanie\Documents\Proj\tonewatch`. Don't describe work you haven't done.
