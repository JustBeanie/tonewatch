# Brief: IC-B-fix — icad2mqtt library: tzdata crash, page stats, and tests that use your fixtures

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a226-06db-7383-af2c-b654e46459e4`) · **Model:** gpt-5.6-luna, medium
**Repo:** `JustBeanie/icad2mqtt` (Go). **Work dir:** worktree `C:\Users\beanie\Documents\Proj\icad2mqtt-icb`, branch `ic-b`.
**Gates:** `go test ./...`, `go vet ./...`, `gofmt -l internal` (empty). Go 1.27.0 lives at `C:\Program Files\Go\bin`; use the same `.gocache/` variables as before.
**Scope:** unchanged. Only `internal/{parse,normalize,model,diff}` and `testdata/` (plus `go.mod`/`go.sum`/`.gitignore`). Don't touch IC-A files.

## Verdict on IC-B: FAIL (one crash bug, missing page contract, tests don't exercise the fixtures)
**PM verified and kept:**
- Coverage: parse 96.0, normalize 90.5, model 100, diff 97.3.
- `go vet` clean; `gofmt -l internal` empty.
- Label-based header discovery with typed `PageError` reasons.
- The category rule table with a word-boundary regex; `key`.
- `ParseTime` round-trip rejection of nonexistent times, with Go picking the earlier instant for the ambiguous case.
- The 16-hex SHA-256 id over `agency.key|received_at|address_clean|municipality.raw`.
- In-page dedupe, the diff engine lifecycle, and the golden JSON files.
- **Privacy passes:** derived fixtures add no new session tokens, and every incident value is invented.

**Correction to your report:** `gofmt -l .` flagging `main.go`, `main_test.go` and `icad2mqtt/main.go` is **not** a pre-existing issue. Those files are gofmt-clean at `origin/master` (PM checked). The flags come from CRLF working-copy line endings and from `.` walking `.gocache/`. Run `gofmt -l internal` and don't report this as a repo defect.

## Bugs
1. **Crash without tzdata.** `time.LoadLocation("America/New_York")` ignores its error in `ParseTime` and `Updated`, and runs on every call.
   - In a minimal container image with no zoneinfo, `loc` is nil and `time.ParseInLocation` **panics**.
   - **Fix:** load the zone once at package init. Blank-import `time/tzdata` so the binary embeds the database (this is stdlib; no new module). Return a typed error if loading still fails.
   - **Test:** a load-failure path via an injectable loader, giving an error and no panic, plus a test that the embedded zone resolves.
2. **No page contract.** Nothing turns a parse `Result` into a `model.Snapshot` with stats. The brief required `page_updated_at` = null plus a **counted warning** when "Updated:" can't be parsed, and drop **reasons**.
   - **Add** `normalize.Page(res parse.Result, fetchedAt time.Time) (model.Snapshot, Stats)`.
   - `Stats` fields:
     - `SkippedRows` (from parse)
     - `Dropped` map[reason]int, with at least `nonexistent_local_time` and `invalid_time`
     - `Duplicates`
     - `Warnings` []string (`page_updated_at_unparsable`)
   - `Normalize` must report per-reason counts, not one integer.
3. **`ZeroStructure` is never returned.** Either return it where the brief says (a header found but no usable table structure at all) and test it, or delete the reason and document why. A header-only table must parse as a valid empty page (zero rows, no error).
4. **Minor:**
   - Compile each rule regex once (package-level), not on every `word()` call.
   - `state police` and `rescue squad` use a substring match without a boundary. Put them through the same boundary regex.
   - Document rule precedence in `doc.go`, e.g. "Fire & EMS" → fire and "Fire Police" → fire, with a test for each.

## Tests (mandatory; the report maps test name to item)
Tests must **use the fixtures and goldens you built**; right now none of the 8 derived fixtures or 3 goldens is read by any test.
- **T1.** Table-driven over every `testdata/events_*.html`, through `parse.Parse` → `normalize.Page`, asserting exact expected results:

  | Fixture | Expected |
  |---|---|
  | normal | 11 rows / N incidents; `page_updated_at` exact |
  | empty | 0 incidents, no error |
  | missing_header | `PageError{NoHeader}` |
  | short_row | `SkippedRows == 1` and others kept |
  | entities | `&amp;` → `&`, NBSP → space in the resulting fields |
  | spring_gap | `Dropped["nonexistent_local_time"] == 1` |
  | fall_ambiguous | earlier instant, exact RFC 3339 with `-04:00` |
  | duplicate | `Duplicates` exact |
  | type_changed | parses; used by T5 |

- **T2. Goldens byte-compared:** `golden_normal.json` equals `json.Marshal(Page(normal))`, with an injected `fetchedAt` and id values stable, via a `-update` flag. Also `golden_event_new.json`, and `golden_snapshot.json` for the empty page. Assert `municipality.name` is `null` and `page_updated_at` is `null` when unparsable (present as null, never absent).
- **T3. Category:**
  - every agency name present in `events_all.html`, listed explicitly
  - `EMS`, `Medical`, `State Police`, `Sheriff`
  - the boundary negatives `Firestone Plaza Security` → unknown and `Emsworth Shop` → unknown
  - the precedence cases from bug 4
- **T4. Exact id:** recompute the SHA-256 of a hand-built `key|rfc3339|ADDR|MUNI` string in the test and compare it to `Incident(...).ID`.
- **T5. Diff with real pages:** normal → type_changed through `Page`, giving exactly one `updated` event for the changed id, with no new/closed noise.
  - A cross-streets-only change gives `updated`.
  - An id leaving the page gives `closed` with the last known fields and `status:"closed"`, then no further event.
  - A page error (missing_header) produces no diff call; show the caller pattern in an example test.
- **T6.** Unparsable "Updated:" on an otherwise good page gives a null `page_updated_at` plus the warning, and no error.
- **T7.** Bug 1 tests; bug 3 test.

## Evidence
- Per bug: the failing test line first, then the passing line and a diff excerpt with file:line.
- `go test -cover ./internal/...` output, which must stay ≥ 90% per package; `go vet ./internal/...`; and `gofmt -l internal` (empty).
- One snapshot and one event JSON produced by T2, pasted (invented values only).

## Standing rules
- Never commit or push. No real incident data. No new modules (`time/tzdata` is stdlib).
- Don't edit anything under `C:\Users\beanie\Documents\Proj\tonewatch`. Don't describe work you haven't done.
