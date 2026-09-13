# Brief: M17a — structured incident JSON in icad2mqtt

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium
**Repo:** this is **`JustBeanie/icad2mqtt`** (Go), NOT ToneWatch. **Work dir:** the local clone `C:\Users\beanie\Documents\Proj\icad2mqtt`, branch `m17a` (based on `origin/master`).
**Gates for this repo** (they replace `just check`): `go test -race ./...`, `go vet ./...`, and `gofmt -l .` with empty output, plus `golangci-lint run` if it is installed. To keep builds inside the sandbox, set `GOCACHE`, `GOMODCACHE` and `GOPATH` to directories under `.gocache/` in the work dir, and gitignore `.gocache/`.

## Goal
Implement `PLAN.md` M17.1 in the ToneWatch repo (the text is quoted below): icad2mqtt parses the CAD events page into a versioned JSON contract that ToneWatch will consume. Existing users keep the raw HTML topic.

## Context
- `main.go` polls `https://911events.ongov.net/CADInet/app/events.jsp` and publishes the whole HTML body to `MQTT_TOPIC` (default `911/cad/events`, QoS 1, not retained) when it changes. The Home Assistant add-on in `icad2mqtt/` wraps it.
- **The page (verified by the PM on 2026-09-12):**
  - Several nested tables, and an "Updated:" row whose text looks like `Sunday, September 13, 2026 1:39 AM`.
  - A header row with cells `Agency | Date/Time | (blank) | Address | (blank) | Cross Streets`.
  - Incident rows with 6 cells: agency name, `MM/DD/YY HH:MM` in local Eastern time, incident type, address, municipality code, cross streets.

## Required
1. **Parser (`cad/parse.go` or similar, test-first).**
   - Use `golang.org/x/net/html`, the only new dependency allowed; pin it in go.mod and go.sum.
   - Locate the incident table by its header labels (`Agency`, `Date/Time`, `Address`, `Cross Streets`), never by table index. Map the two blank header columns to `type` and `municipality` by position relative to those labels.
   - Collapse whitespace, unescape entities, and bound every string to 256 bytes.
   - Parse `received_at` and `page_updated_at` in `America/New_York`. Import `time/tzdata` so the scratch/non-root image works without system zoneinfo. Output RFC 3339 with the offset.
   - Across DST, an ambiguous or nonexistent local time resolves deterministically; document the rule and test both transitions.
   - If the header row is missing, or a row doesn't have the expected column count, don't publish the snapshot. Log a single counter-style line (no incident contents), and keep the last good snapshot.
2. **Contract (topic base `MQTT_BASE_TOPIC`, default `911/cad`).**
   - **`<base>/incidents`:** retained, QoS 1, published only when the incident set changes. It carries `{"schema":1,"source":"ongov-911events","page_updated_at":…,"fetched_at":…UTC,"incidents":[…]}`, sorted by `received_at`, then `id`.
   - **`<base>/incident`:** not retained, QoS 1. It carries `{"schema":1,"event":"new"|"updated"|"closed","incident":{…}}`, computed by diffing against the previous good snapshot.
     - Closed means gone from the page; the event carries the last known fields with `status` `closed`.
     - On startup the first snapshot publishes, but emits no `new` flood: the first poll only seeds state. Document this.
   - **Incident object:** `id`, `agency`, `received_at`, `type`, `address`, `municipality`, `cross_streets`, `status` (`active`/`closed`).
     - `id` is the first 16 hex chars of SHA-256 over `agency|received_at|address|municipality`.
     - A change to `type` or `cross_streets` on the same id is `updated`.
   - **Compatibility:** keep publishing raw HTML to `MQTT_TOPIC` exactly as today when `PUBLISH_RAW` is `true`, which is the default.
   - Add the new options (`mqtt_base_topic`, `publish_raw`) to `icad2mqtt/config.yaml` and `run.sh`. Keep the add-on schema valid.
3. **Fixtures.** Fetch the live page **once** to confirm the structure. **Do not commit real incident data** (real agencies are fine; real addresses, types and times are not). Build `testdata/*.html` fixtures that copy the real markup structure but carry invented streets, types and times. Cover:
   - a normal page
   - an empty incident list
   - a missing header
   - a short row
   - entity-escaped text
   - a DST-edge timestamp
   - an incident whose type changes between two pages
4. **Tests.**
   - Parser golden tests against fixtures.
   - Diff tests for new, updated and closed, plus the startup seed.
   - A publish test with the existing fake publisher: retained flag and QoS per topic, no publish when unchanged, and raw topic compatibility on and off.
   - A JSON schema shape test.
5. **Docs.**
   - README: document the contract as a stable, versioned interface (field table, topics, example payloads with invented data).
   - Add `docs/contract.md` or a README section. State that ToneWatch consumes schema 1.
   - Note the privacy aspect: incident addresses are published to the broker, and retained on the snapshot topic.

## Standing rules
- Never commit or push; the PM reviews and asks the user before anything is pushed to this public repo.
- Never weaken CI (`.github/workflows/ci.yml`, `.golangci.yml`).
- No real incident data in commits, tests, docs or logs.
- Don't change the Docker base images or unrelated dependencies.

## Definition of done
- `go test -race ./...`, `go vet ./...` and `gofmt -l .` (empty) all pass; paste their output. Include `golangci-lint run` if available, or say it isn't installed.
- `docker build` isn't required. Do confirm `time/tzdata` is imported, and why.
- The final report lists every changed file, the exact JSON contract with one invented example of each payload, the DST rule, and how the live page structure was verified (the date/time you fetched it, the header labels found). No incident contents.
