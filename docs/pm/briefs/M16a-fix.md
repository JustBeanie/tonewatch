# Brief: M16a-fix — agencies review findings (new thread)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m16a`, which already contains the M16a implementation. Build on it; don't start over. **E2E port:** `TONEWATCH_E2E_PORT=8805`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.

## Verdict on M16a: FAIL (spec: tests + three bugs)
**Keep as-is:**
- the models and GeoJSON validator
- migration 0005
- the call snapshot in persistence, which is hot-applied through `Supervisor.reload`
- the agencies route (auth, CSRF, audit, 409 on a referenced delete)
- the per-response CSP from `app.state.config`
- the `agencies=`/`map=` plumbing in the importer and add-on supervisor, which was necessary

**Evidence rule:** every fix needs (1) the red-first failure line of a new test, (2) the passing line, and (3) a short diff excerpt with file:line. A report that claims work without that evidence is rejected. **Never run `git add`/`git commit`** (the last run tried to stage files); api-drift against uncommitted generated files is handled by the PM.

## Bugs
1. **Stale agency on events after an agency-only edit.**
   - **Cause:** `Supervisor._run_source` injects `channel.agencies` only at channel start, and `reload` restarts channels only when sources, tone sets or discovery change. Renaming or moving an agency leaves running channels emitting the old agency in `ToneDetected.agency`; the WS serializes that via `asdict`.
   - **Made worse by:** the dispatcher prefers `event.agency` over the current config.
   - **Fix:** give `Channel` an `agency_lookup: Callable[[str], dict[str, Any] | None]` bound to the supervisor's *current* config, resolved at detection time. Remove the `hasattr(channel, "agencies")` injection. The dispatcher builds the payload from its current config (updated in `reload`) and never from a stale event copy.
   - **Test:** start a channel, change only an agency's name through `Supervisor.reload`, then trigger a detection. The WS event and the dispatcher payload both carry the new name, with no channel restart.
2. **Config rebuilds silently drop fields: a class of bug.**
   - `importers/tones_cfg.py:359` and `integrations/supervisor.py:36` rebuild `AppConfig` field by field and **omit `discovery`**, so a tones.cfg import or add-on MQTT setup resets discovery settings to defaults. This predates M16a, but M16a added two more fields that every such site must remember.
   - **Fix:** add one helper, e.g. `config.store.replace_config(config, **changes) -> AppConfig`, that validates `AppConfig.model_validate({**config.model_dump(), **changes})`. Replace **every** field-by-field `AppConfig(...)` rebuild with it: `deps.py`, `routes/config.py` (both sites), `routes/agencies.py`, the importer, and the add-on supervisor.
   - **Test:** parametrize over `AppConfig.model_fields`, then run each mutation path (tone-set CRUD, source CRUD, alert-target CRUD, agency CRUD, tone-set delete, tones.cfg apply, add-on MQTT target). Every untouched field must survive unchanged. Add a non-default value for each field so defaults can't mask loss.
3. **Tile URL host templates break the CSP.** `https://{s}.tiles.example/{z}/{x}/{y}.png` passes `MapConfig` validation, but the CSP origin becomes `https://{s}.tiles.example`, which is invalid.
   - **Fix:** reject `{` or `}` in the netloc with a clear message (subdomain templates aren't supported).
   - **Test:** that case, plus `https://tiles.example:8443/...` (rejected) and `https://tiles.example:443/...` (the CSP origin has no `:443` duplication issue; assert the exact header).

## Cleanups
- Remove the `item_id == "geojson"` special case in `get_agency`; an agency with id `geojson` must be reachable. Test it.
- Restore the deleted `_set_api_csp` docstring and remove the stray blank line in `create_app`. Make no unrelated edits.

## Required tests still missing (from the M16a brief; all mandatory)
- `AppConfig` rejects a tone set whose `agency_id` references a missing agency (422 through the tone-set API naming the id).
- **Coverage validation:** MultiPolygon (valid and invalid), the 256 KB serialized limit, `bool` coordinates rejected, NaN/inf rejected, and a hole ring.
- **Migration 0005:** upgrade and downgrade on a real SQLite file via Alembic (columns exist after upgrade, gone after downgrade, existing rows kept).
- **Call snapshot survives:** persist a call for a tone set linked to an agency, then rename the agency and delete it (after unlinking). Call list and detail still show the original `agency {id, name, kind}`, and `?agency_id=` still filters it.
- **Event payloads:** dispatcher payload (`agency` with `id, name, short_name, kind, lat, lon`), the MQTT call topic JSON, the webhook JSON body, and the HA discovery `event` entity payload each include the agency, or `null` when unlinked. This is additive: assert the existing fields are unchanged.
- **CSP at app level:** a GET for an HTML route with an empty `map.tile_url` has no external origin. After saving a map config through the store/reload path, the next HTML response has exactly that one origin in `img-src` and nowhere else. API (JSON) responses keep the deny-all CSP.
- **GeoJSON shape:** the Point order is `[lon, lat]`, station features carry `station_of`, and the coverage feature appears once. An agency without stations or coverage yields exactly one feature.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification.
- Never print or commit private fixtures. Use only invented agency names and coordinates.
- Never `git add`, commit or push.

## Definition of done
- For every bug and cleanup, the report shows the red-first line, the passing line and a diff excerpt.
- `just check` passes. Paste the pytest and vitest summary lines; the pytest count must rise by the number of tests you added (state both numbers).
- `just ci-local` with port 8805 passes up to api-drift. If api-drift fails only on uncommitted generated files, paste `git diff --stat -- web/src/api`.
- The report maps each new test name to the requirement it covers.
