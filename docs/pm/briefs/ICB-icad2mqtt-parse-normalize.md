# Brief: IC-B — icad2mqtt parsing, cleaning, schema v1 model and diff (library packages only)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium
**Repo:** **`JustBeanie/icad2mqtt`** (Go), NOT ToneWatch. **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-icb`, branch `ic-b` (from `origin/master`).
**Gates** (they replace the dispatcher's `just check`):
- `go test ./...`
- `go vet ./...`
- `gofmt -l .` with empty output
- `golangci-lint run`, if it's installed

`-race` needs cgo, which is missing on this host, so race tests run in GitHub CI.
**Go caches:** set `GOCACHE`, `GOMODCACHE`, `GOPATH` and `GOTMPDIR` to directories under `.gocache/` in the work dir, and gitignore `.gocache/`.
**Go toolchain:** Go 1.27.0 is installed at `C:\Program Files\Go\bin\go.exe`. Prepend that directory to PATH in every shell, because your environment may predate the install. The PM pre-downloaded the module cache, including `golang.org/x/net`, into `.gocache/` using exactly those variables.

## Context
- **Read first:** the reviewed plan `C:\Users\beanie\Documents\Proj\tonewatch\docs\pm\reports\M17-icad2mqtt-plan-20260912-234423.md` (sections 2–5, 7; tasks IC5–IC8, IC10), and the PM's verified page facts in `C:\Users\beanie\Documents\Proj\tonewatch\docs\pm\carryover.md` section "M14–M18 kickoff".
- **Scope:** you build **pure library packages only**: `internal/parse`, `internal/normalize`, `internal/model`, `internal/diff`, plus `testdata/`.
  - **Do not edit `main.go`, config, Dockerfiles, the add-on folder or CI.** Another engineer (IC-A) is changing those in parallel.
  - Your only permitted edits to existing files are `go.mod`/`go.sum` (adding `golang.org/x/net`) and `.gitignore`.
- **Page fixture.** Your sandbox can't reach the live page. The PM built a fixture from the real page markup with **invented** incident values, and placed it in your worktree at `testdata/events_all.html` (ISO-8859-1 bytes, as served).
  - Treat its structure as ground truth. Don't regenerate or re-fetch it.
  - Verified clean: no real incident values; the footer timestamp and session ids are replaced.
  - It keeps the real agency names, which are public bodies; everything else is invented.
  - Derive all other fixtures from it by editing values, never by fetching.
- **Verified facts about the page:**
  - ISO-8859-1.
  - The incident table is nested 4 levels deep.
  - Header cells are `Agency | Date/Time | (blank) | Address | (blank) | Cross Streets`.
  - Incident rows have 6 `<td>` cells: agency, `MM/DD/YY HH:MM`, type, address, municipality code, cross streets.
  - An "Updated:" row holds text like `Sunday, September 13, 2026 12:10 AM`.
  - The category tabs are session-bound links and are **not** used.

## User decisions (binding)
- **Category is derived from the agency name** (one request per poll; no tab fetching).
- HA discovery will expose only per-category counts (IC-C). Your model just needs the category enum.

## Required
1. **`internal/parse`** (input: UTF-8 page text, since IC-A decodes Latin-1).
   - Use `golang.org/x/net/html` (the only allowed new module).
   - Find the header row by normalized labels. Map the two blank columns by position relative to the labeled ones.
   - Return raw rows (6 strings each) plus the raw "Updated:" text.
   - **Page-level failure** (typed error with a reason enum): no header, duplicate conflicting headers, or zero parseable structure.
   - **Row-level problems** (wrong cell count) skip the row and are counted, not fatal.
   - Normalize cell text: entity-decode, NBSP to space, collapse Unicode whitespace, trim.
2. **`internal/normalize`** (test-first, table-driven).
   - **Agency:** `name` is the cleaned display form; `key` is a case-folded match key.
   - **`category`**, enum `fire|ems|police|other|unknown`. Word-boundary rules:
     - Fire, when the name contains `Fire`
     - EMS, when it contains `EMS`, `Ambulance`, `Medical` or `Rescue Squad`
     - Police, when it contains `Police`, `Sheriff` or `State Police`/`Troop`
     - otherwise `unknown`

     Rules live in one table with tests for every fixture agency. Also set `category_source: "agency_name"`.
   - **Type:** `raw` and a `key` (lowercase, punctuation to `-`, collapsed). **No code/description split in v1:** the observed values have no reliable delimiter, so leave `code` absent. Document it as a heuristic you deliberately didn't apply.
   - **Address:** `address_raw` and a conservative `address_clean` (whitespace, uppercase). **No street/place split in v1**, for the same reason.
   - **Municipality:** `raw` code; `name` is `null`. There is no authoritative mapping yet; leave a documented hook.
   - **Cross streets:** `cross_streets_raw`, plus `cross_streets` split on ` & ` (trimmed, empties removed, order kept). An empty cell gives `[]`.
   - **Time:** `received_at_raw`, and `received_at` in RFC 3339 in `America/New_York`.
     - **DST, nonexistent** (spring-forward gap): **drop that row** with reason `nonexistent_local_time`.
     - **DST, ambiguous** (fall-back): pick the **earlier** instant.

     Test both with invented dates. Parse the "Updated:" text into `page_updated_at` with the same rules; an unparsable page timestamp gives null plus a counted warning, not a page failure.
   - **ID:** the first 16 lowercase hex characters of SHA-256 over `agency.key|received_at|address_clean|municipality.raw`.
   - **Dedupe** within a page by id; the first occurrence wins, and duplicates are counted.
3. **`internal/model`: schema v1 types.**
   - **Snapshot:** `{schema:1, source:"ongov-911events", page_updated_at, fetched_at, incidents:[…]}`, with incidents sorted by `received_at`, then `id`.
   - **Event:** `{schema:1, event:"new"|"updated"|"closed", incident}`.
   - **Incident:** `id`, `agency{name,key,category,category_source}`, `received_at`, `received_at_raw`, `type{raw,key}`, `address_raw`, `address_clean`, `municipality{raw,name}`, `cross_streets_raw`, `cross_streets`, `status`.
   - **Tests:** JSON field names are stable (golden JSON), output order is deterministic, and `null` vs absent is handled explicitly.
4. **`internal/diff`** (test-first).
   - `Diff(prev, next)` returns events.
   - **new:** an id not seen before.
   - **updated:** the same id with a changed `type.raw` or `cross_streets_raw`.
   - **closed:** an id that has left a **valid** next snapshot. The event carries the last known fields with `status: closed`.
   - **First call:** with no previous snapshot, seed only (no events).
   - Closed incidents are forgotten after one closed event (bounded memory).
   - A failed page never produces a diff; the caller keeps the previous snapshot. Document it.
5. **Fixtures (`testdata/`).** Derived from `events_all.html`:
   - normal
   - empty table (header only)
   - missing header
   - one short row among good rows
   - entity-escaped text (`&amp;`, NBSP)
   - spring-forward gap time
   - fall-back ambiguous time
   - the same incident with a changed type (a second page)
   - a duplicate row

   Plus golden JSON outputs for normal and event sequences.
6. **Package docs.** A `doc.go` per package that states every heuristic and its failure mode.

## Standing rules
- Never commit or push.
- **No real incident data:** only the PM fixture's invented values or values you invent.
- **No other new dependencies.** Don't touch files owned by IC-A.
- Never weaken lint config. Don't edit anything under `C:\Users\beanie\Documents\Proj\tonewatch`.

## Definition of done
- `go test ./...`, `go vet ./...` and `gofmt -l .` all pass; paste the output. Include `golangci-lint run` if installed, or say it isn't.
- Coverage for the four packages is at least 90% (`go test -cover`); paste it.
- The final report lists every file, the category rule table, the ID and DST rules, one invented snapshot and one invented event JSON produced by a test, and any structure in the fixture you found surprising.
