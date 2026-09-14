# Brief: M16a-rebase — resolve agencies conflicts over live restream + squelch

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a1ba-d1c6-7ce0-8b17-b72f382b9ee3`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m16a`. **E2E port:** `TONEWATCH_E2E_PORT=8805` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## Verdict on M16a-fix2: PASS on tests, with one weak test
- **PM verified:**
  - `test_supervisor_agency_only_reload_keeps_channel_and_updates_payload`: same task object, late-bound lookup, dispatcher current config.
  - Migration 0005 round trip.
  - The call snapshot through the real API with a real SQLite DB.
  - App-level CSP through `PUT /api/config`.
  - The `geojson` id route.
  - 422 naming the missing id.
  - MultiPolygon, hole, bool and non-finite cases.
  - MQTT/webhook payloads.
  - The exact docstring.
- **Weak:** `test_all_config_mutation_paths_preserve_untouched_fields` only calls `replace_config` with the owner field. It never drives the real paths, so the 14 path labels are cosmetic. Fix it in item 3.

## What changed: the PM already did the git steps
- `main` gained **M14a live restream** (`c0e2305`) and **M15a squelch** (`f643f97`). Your sandbox can't write git metadata in this worktree, so the PM ran:
  - backup to `Proj/pm-backups/m16a-premerge-*`
  - `stash -u` → `merge --ff-only origin/main` (HEAD `05f0544`) → `stash pop`, then `git reset` to clear the unmerged index
- **11 files contain conflict markers:**
  - `backend/src/tonewatch/api/deps.py` (1)
  - `backend/src/tonewatch/api/routes/config.py` (2)
  - `backend/src/tonewatch/importers/tones_cfg.py` (1)
  - `backend/src/tonewatch/integrations/supervisor.py` (1)
  - `backend/src/tonewatch/pipeline/channel.py` (1)
  - `backend/src/tonewatch/pipeline/supervisor.py` (1)
  - `docs/security/asvs/checklist.csv` (2)
  - `docs/security/threat-model/tonewatch.json` (1)
  - `mkdocs.yml` (1)
  - `web/src/api/generated/schema.d.ts` (2) and `web/src/api/openapi.json` (2): **don't hand-merge these; regenerate them** with `just gen-api` after the backend resolves.
- **Don't run any git command that writes** (fetch, stash, merge, rebase, checkout, reset, add, commit). Read-only `git diff`/`status`/`show origin/main:<path>` is fine.

## Required
1. **Resolve every marker, keeping all three features:**
   - **`AppConfig` rebuild sites** (deps, config routes, importer, add-on supervisor): main now rebuilds field by field with `live_stream=`. **Keep your `replace_config(...)` call**, and delete the field-by-field version entirely. `replace_config` carries `live_stream`, `discovery`, `map`, `agencies` and every future field automatically.
   - **`api/routes/config.py`:**
     - Source list and detail keep main's `squelch_open`, `last_activity_at` and `live_listeners` (with null guards).
     - The route handler `replace_config` vs. the imported helper name collision stays resolved: the helper is imported as `rebuild_config`, or rename the handler.
   - **`pipeline/channel.py`:** keep main's `live_hub`/`_feed_live(gate_open=...)` and all squelch wiring (level, watchdog, `SquelchChanged`, `stop_on_squelch`), **and** your `agency_lookup` param used at detection time.
   - **`pipeline/supervisor.py`:** channels get `live_hub`, squelch settings, **and** `agency_lookup` late-bound to `self.config`. The `reload` diff logic keeps main's behavior. An agency-only change must still **not** restart channels.
   - **`docs/security/*`:** keep both sides' rows. Re-derive every ASVS line anchor that moved, following the conventions (quote-all CSV, LF, line = newline count before the unique snippet). `threat-model/tonewatch.json` must stay valid JSON with both sides' entries; `test_asvs_checklist` must pass.
   - **`mkdocs.yml`:** the nav keeps main's pages (listen live, squelch/tuning) **and** your agencies guide.
   - Afterwards `grep -rn '^<<<<<<<\|^=======$\|^>>>>>>>' backend web/src docs mkdocs.yml` prints nothing (paste it).
2. **Also check the clean auto-merges:** `models.py` (`SourceBase` has `squelch`, `live_stream_enabled`; `ToneSet.agency_id`; `AppConfig` has `live_stream`, `agencies`, `map`), `dispatcher.py`, `persistence.py`, `events.py`, `app.py` (CSP from `app.state.config`, plus the live and agencies routers both registered), and `docs/PROGRESS.md` (main's M14 and M15 `[x]` rows stay; your M16 rows stay PENDING-REVIEW).
3. **Make the mutation-path test real.** Rewrite `test_all_config_mutation_paths_preserve_untouched_fields` so each parametrized path **drives the actual code path**:
   - tone-set/source/alert-target/agency create, update and delete through the ASGI API with auth
   - tones.cfg apply through the importer's apply function (invented synthetic content only)
   - the add-on MQTT target through the `integrations/supervisor.py` function

   The starting config must have a non-default value for **every** `AppConfig` field, now including `live_stream`, and keep the `set(values) == set(AppConfig.model_fields)` guard. Assert every non-owner field is unchanged afterwards. **Prove it's real:** temporarily revert one site to a field-by-field rebuild that omits `discovery`, paste the failing line, then restore it.
4. **Regression across the merged features,** through `Channel`: a tone set linked to an agency, with squelch `level` mode and a fake live hub. `ToneDetected.agency` is populated, live `gate_open` follows squelch, and detection times are unchanged from mode `off`. One test.
5. **Regenerate** the web client with `just gen-api`, and compile `Sources.tsx` with minimal type fixes only.

## Gates and evidence
- Each conflicted file with a one-line resolution summary, and the empty marker grep.
- The red line from the item 3 proof and the passing line; the passing line for item 4.
- The pytest count: main is **441 passed + 3 skipped** at `f643f97`, and your branch was 445 + 4 before the merge. State the merged count; it should be about main + your M16a tests.
- `just check`, `just e2e` (port 8805), `just ci-local` up to api-drift, and `git diff --stat -- web/src/api`.
- `git diff origin/main -- backend/tests/unit/test_s4_security.py` must be empty.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate or edit existing security tests.
- Invented agency names and coordinates only.
- Never write git state. Don't describe work you haven't done.
