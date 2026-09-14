# Brief: M18a-fix4 — Meshtastic: resolve conflicts over restream, squelch and agencies, then the last mandatory tests

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a1c3-42b9-7691-ab5a-f764e7d4bf78`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m18a`. **E2E port:** `TONEWATCH_E2E_PORT=8806` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest errors with `PermissionError ... pytest-of-Beanie`, add `--basetemp backend/.pytest-tmp` (never commit it).
**Git:** never write git state. Read-only `diff`/`status`/`show origin/main:<path>` is fine.

## Verdict on M18a-fix3: PARTIAL (honest report, thank you)
**PM verified on the host:**
- `tests/integration/test_app_wiring.py` + `tests/unit/test_meshtastic.py`: **37 passed**, so the regression is fixed.
- The embedded-broker test drives the real `AlertDispatcher` with topic `msh/US/2/json/mqtt/`, QoS 1 and retain false.
- The route contract is `{ok, error}`.
- New tests: phases (no coalescing of `recording_ready`), template reload, target timeout, recording stored after close.
- `test_s4_security.py` has no diff.

**Still missing (you listed four of these yourself):**
- the race test (2)
- the stacked two-agency case (12)
- real-SQLite `rate_limited` rows (8)
- timezone fallback cases (11)
- the real-dispatcher `test_target` audit (13)
- API secret masking (14)

## The PM already did the git steps
- `main` gained **M14a live restream** (`c0e2305`), **M15a squelch** (`f643f97`) and **M16a agencies** (`8d4b5b5`). The PM ran: backup to `Proj/pm-backups/m18a-premerge-*`, `stash -u`, `ff-only` to `11472da`, `stash pop`, then `git reset`.
- **Conflict markers, by file (count):**
  - `backend/src/tonewatch/alerts/dispatcher.py` (1)
  - `backend/src/tonewatch/api/routes/config.py` (1)
  - `backend/src/tonewatch/config/models.py` (2)
  - `docs/security/asvs/checklist.csv` (1)
  - `mkdocs.yml` (1)
  - `web/src/api/generated/schema.d.ts` (1) and `web/src/api/openapi.json` (1): **regenerate** with `just gen-api`; don't hand-merge.
- Untracked and present: `alerts/meshtastic.py`, `tests/unit/test_meshtastic.py`, ADR 0012, `docs/guide/meshtastic.md`.

## Required
1. **Resolve every marker, keeping all features:**
   - **`dispatcher.py`:**
     - Keep main's agency handling. `state["agency"]` is built from the **current config** (`id, name, short_name, kind, lat, lon`) and `reload` updates `self.config`.
     - Keep all your Meshtastic coalescing, follow-up, prune, phase and timeout logic, plus the close/recording ordering fix.
     - `render_message` reads that agency dict. Stacked calls may carry several tone sets from different agencies, so decide and document how `{agency}`/`{agency_short}` render then (e.g. unique short names joined by `/`), and test it (item 3).
   - **`models.py`:**
     - `AppConfig` keeps `live_stream`, `agencies`, `map` and your alert-target union including `MeshtasticTarget`.
     - `SourceBase` keeps `squelch` and `live_stream_enabled`.
     - `ToneSet` keeps `agency_id`.
   - **`api/routes/config.py`:** every config rebuild uses main's `rebuild_config` (`replace_config`); **never** reintroduce a field-by-field `AppConfig(...)`. Keep main's source status fields and calibrate-free state. Keep your `alert_target_test` route with its `{ok, error}` contract and audit.
   - **`checklist.csv`** (re-derive moved anchors: quote-all, LF, line = newline count before the unique snippet) and **`mkdocs.yml`** (keep Listen live, Agencies **and** Meshtastic in the nav).
   - The marker grep `grep -rn '^<<<<<<<\|^=======$\|^>>>>>>>' backend web/src docs mkdocs.yml` must be empty (paste it).
   - `main`'s `test_all_config_mutation_paths_preserve_untouched_fields` must still pass. Add a Meshtastic target create path to its parametrization.
2. **Check the clean auto-merges:** `channel.py`/`supervisor.py` (live hub, squelch, `agency_lookup`), `events.py`, `ha_discovery.py`, `persistence.py`, `app.py` routers, and `docs/PROGRESS.md` (main's M14/M15/M16 `[x]` rows stay; your M18 rows stay PENDING-REVIEW).
3. **The last mandatory tests** (numbering from M18a-fix2; the report maps test name to number):
   - **2. Race:** a sender blocked on an `asyncio.Event`; a tone set arriving while the first send is in flight goes out as exactly **one** follow-up and is never lost.
   - **8. Rate-limit rows:** a real temp SQLite session factory (`create_database` + schema). `min_interval_s` and `max_per_hour` each yield exactly **one** `AlertAttempt` row with error `rate_limited` and no retries.
   - **11. Timezone:**
     - a fixed UTC instant with `timezone="America/New_York"` gives the exact `HH:MM`
     - unset + `TZ=Europe/Berlin` (monkeypatch) is honoured
     - unset + no `TZ` gives UTC
     - an invalid IANA name is rejected by the model
   - **12. Agency, stacked:** a stacked call with tone sets linked to **two different agencies** renders per item 1, with no `{`, `[` or `'id'`. Extend the existing absent/None test so it also covers "absent".
   - **13. `test_target`, real dispatcher:** real `AlertDispatcher` + fake sender + real temp DB via the ASGI route. Assert:
     - exactly one send
     - **zero** `AlertAttempt` rows
     - exactly one `alert_target_test` audit row carrying the target id and `ok`, and no secrets
     - a failing sender's error surfaced
     - a slow sender times out at the target timeout
   - **14. Secrets:** create a Meshtastic target with an inline broker `password` through the API. `GET /api/alert-targets` and `GET /api/alert-targets/{id}` return it masked. Audit before/after for the create and an update never contain the plaintext. Use a new test file and keep `test_s4_security.py` unchanged.
4. **Merged-feature regression:** one dispatcher test with a tone set linked to an agency, a Meshtastic target, and an agency rename via `reload` during the coalescing window. The single mesh message uses the **renamed** agency, and the MQTT call payload also has the renamed agency.

## Gates and evidence
- Each conflicted file with a one-line resolution summary, and the empty marker grep.
- For each item 3 test and item 4, the first-run line (failing, or "passes immediately" stated explicitly) and the passing line.
- The pytest count on `main` (**484 passed + 3 skipped** at `8d4b5b5`) and after.
- `just check`, `just e2e` (port 8806; if the launcher hangs after 4 specs pass, paste that line and continue) and `just ci-local` up to api-drift, plus `git diff --stat -- web/src/api`.
- `git diff origin/main -- backend/tests/unit/test_s4_security.py` must be empty.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification.
- No new dependencies, and nothing from the GPL `meshtastic` package or its protobufs. Invented node ids and names only.
- Never write git state. Don't describe work you haven't done.
