# Brief: IC-C — icad2mqtt structured publishing, availability/health, HA discovery counts, contract docs

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Repo:** `JustBeanie/icad2mqtt` (Go). **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-icc`, branch `ic-c`.
- It is `master` with **IC-B** (`internal/{parse,normalize,model,diff}`, fixtures, goldens) and **IC-A** (`internal/{config,fetch}`, main wiring, add-on options, backoff) already merged and reviewed.
- **Don't re-implement** those packages. Extend them only where this brief says.

**Gates:**
- `go test ./...`, `go vet ./...`
- `gofmt -l $(git ls-files '*.go') internal`, which must be empty
- in `icad2mqtt/`: `go vet ./...` + `go build`

Go 1.27.0 is at `C:\Program Files\Go\bin`. Set `GOCACHE`/`GOPATH`/`GOTMPDIR` under `.gocache/` in the work dir, and point `GOMODCACHE` at `C:\Users\beanie\Documents\Proj\icad2mqtt-icb\.gocache\mod`, which is a verified cache: **read-only, never modify it**. Also set `GOFLAGS=-mod=mod` and `GOPROXY=off`.

**Git:** never write git state. **🚨 Never modify anything under any `.gocache/`.**

## Read first
- Plan report `C:\Users\beanie\Documents\Proj\tonewatch\docs\pm\reports\M17-icad2mqtt-plan-20260912-234423.md`, sections 5 (output contract), 6, 9, and tasks IC9 and IC11.
- The package docs in `internal/*/doc.go`.
- `normalize.Page`, `diff` engine, `fetch.Fetcher`, and `config.Config` (`MqttBaseTopic`, `PublishRaw`, `HADiscovery`).

## User decisions (binding)
- **Raw HTML publishing:** stays on by default (`PUBLISH_RAW=true`) and behaves exactly as today.
- **HA MQTT discovery:** opt-in (`HA_DISCOVERY=false`). When on, it exposes **only per-category active-incident counts** (`fire`, `ems`, `police`, `other`, `unknown`, plus `total`). **Never** expose individual incidents, addresses, or cross streets as HA entities or retained discovery payloads.
- **Category:** derived from the agency name (already implemented).

## Required
1. **`internal/publish`** (test-first, with a fake publisher interface; no broker needed for unit tests).
   - **Topics under `<base>` = `MqttBaseTopic`:**

     | Topic | QoS | Retained | Content |
     |---|---|---|---|
     | `<base>/incidents` | 1 | yes | The schema v1 snapshot JSON. Published **only when the incident set or any incident field changes**: compare canonical JSON bytes, not the page hash, because `fetched_at` changes every poll; exclude `fetched_at` from the comparison. |
     | `<base>/incident` | 1 | no | One schema v1 event per `diff` event, in deterministic order. |
     | `<base>/availability` | 1 | yes | `online`/`offline`. |
     | `<base>/health` | 1 | yes | Health JSON (item 3). |

   - **Availability:** set the MQTT **LWT** to `offline` (retained, QoS 1) in the client options, and publish `online` retained on every (re)connect via `OnConnect`.
   - **Raw topic:** unchanged. `MQTT_TOPIC`, QoS 1, not retained, publish-on-change, only when `PublishRaw`.
   - **Payload privacy:** nothing is logged except counts and topic names. No incident fields, addresses or raw HTML ever appear in logs.
2. **Main loop wiring:** on each successful fetch, run `parse.Parse` → `normalize.Page` → `diff` → `publish`.
   - A **page error** (`parse.PageError`) publishes **nothing** structured and doesn't advance diff state. It increments health counters and logs one bounded line (the reason enum only). The raw topic behaviour is unchanged.
   - **First valid snapshot** seeds the diff state and publishes the retained snapshot, but **no** `new` events.
   - **Restarts:** after a restart the process has no memory, so it seeds again. Document that consumers must use the retained snapshot for state and events only for transitions.
   - Wire the `diff` engine's bounded closed-incident memory as designed.
3. **Health JSON:** `{schema:1, status:"ok"|"degraded"|"failing", last_success_at, last_error_at, last_error_reason, consecutive_failures, polls_total, page_errors_total, rows_skipped_total, rows_dropped_total{reason}, duplicates_total, incidents_active, page_updated_at, version}`.
   - `status` is `failing` when `consecutive_failures >= 3`, `degraded` when the last page had skipped or dropped rows or an unparsable `page_updated_at`, and `ok` otherwise.
   - Publish retained on every poll **only when it changed** (ignore timestamps that tick every poll, except `last_success_at`, which may change at most once per poll interval).
   - Never include page content.
4. **HA discovery** (`HA_DISCOVERY=true` only). Retained discovery configs under `homeassistant/sensor/icad2mqtt_<client_id>/<category>_active/config`, one per category plus `total`.
   - Each config has `state_topic` = `<base>/counts`, a `value_template` picking that category, `availability_topic` = `<base>/availability`, `unique_id`, and a `device` block (name `icad2mqtt`, `identifiers` from `client_id`, `sw_version`). Use `state_class: measurement` and an icon per category.
   - Publish `<base>/counts` (QoS 1, retained) as `{fire, ems, police, other, unknown, total}` whenever counts change.
   - When `HA_DISCOVERY` is false at startup, publish **empty retained payloads** to those config topics once, to clear old discovery. Test it.
5. **Add-on duplicate:** the add-on's `icad2mqtt/main.go` is a separate module and **can't import `internal/`**. **Don't port structured publishing into it.** Instead:
   - Leave it building and publishing raw only, as today, with a **startup warning log** when `HA_DISCOVERY=true` or when the structured topics are expected, saying structured output requires the root binary (pending PM decision IC2 packaging consolidation).
   - Document this limitation clearly in the add-on `DOCS`/README section.
   - The PM will ask the user about consolidation separately.
6. **Docs:** add `docs/contract.md` covering:
   - schema v1 (snapshot, event, health, counts)
   - every topic with QoS and retained flags
   - field rules and heuristics (from the `doc.go` files)
   - invented examples only
   - startup seeding and restart semantics
   - privacy (addresses are in the retained snapshot; advise broker ACLs and retention)
   - HA discovery counts only
   - how ToneWatch will consume `<base>/incident`

   Also update the README topics section.

## Mandatory tests (the report maps test name to letter)
- **A. Publish topics and flags:** a fake publisher asserts topic, QoS 1 and the retained flag for snapshot, event, availability, health, counts and raw (on and off).
- **B. Unchanged suppression:** the same page twice (different `fetched_at`) gives one snapshot publish. A type change gives a new snapshot plus exactly one `updated` event.
- **C. Seeding:** the first valid page gives a retained snapshot and zero events. The second page with one new row gives exactly one `new` event.
- **D. Page error:** the `events_missing_header.html` fixture gives no structured publishes, unchanged diff state, `page_errors_total` incremented, and a health status change. Raw still publishes when on.
- **E. Health status transitions:** ok → degraded (short-row fixture) → failing (3 consecutive fetch failures) → ok, with retained publishes only on change.
- **F. HA discovery:**
  - The configs have the exact JSON keys, `unique_id`s and device block, and **no incident fields**. Assert the serialized configs contain none of the fixture's addresses or cross streets.
  - Counts are correct for `events_all.html`.
  - `HA_DISCOVERY=false` publishes empty retained clears.
- **G. LWT and online:** the client options include the LWT (topic, `offline`, QoS 1, retained). `OnConnect` publishes `online` retained.
- **H. Logging privacy:** capture log output over a full fixture poll cycle (all fixtures) and assert that no incident address, type or cross-street string from the fixtures appears.
- **I. End-to-end through `Run`** with an `httptest` server serving `events_all.html` then `events_type_changed.html` (ISO-8859-1 bytes), an injected sleep, and a fake MQTT publisher. Assert the full publish sequence.

## Evidence (the report is rejected without this)
- The test → letter table.
- Per required item 1–4, the failing test line first (test-first), the passing line, and a diff excerpt with file:line.
- `go test -cover ./...` (`internal/publish` ≥ 90 %, main ≥ 60 %), `go vet`, the gofmt command, and the add-on vet and build.
- One invented snapshot, event, health, counts and one discovery config JSON, produced by tests.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same check on `master` code and pasting the result.

## Standing rules
- Never commit or push. No real incident data: use only the invented fixture values.
- No new modules. Don't weaken CI. Never touch `.gocache/`.
- Don't edit anything under `C:\Users\beanie\Documents\Proj\tonewatch`.
- Don't describe work you haven't done.
