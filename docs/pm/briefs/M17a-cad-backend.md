# Brief: M17a — CAD incident feed, correlation and unmatched agencies (M17.2, M17.3, M17.4, M17.6 backend)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m17a` (branch `m17a`). **E2E port:** `TONEWATCH_E2E_PORT=8826` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` "M17: CAD incident correlation via icad2mqtt" (~line 569).
- **The published producer contract**, icad2mqtt v2.0.0 `docs/contract.md`, summarized here (that repo is not in your worktree):
  - **Topics** (all QoS 1):
    - `<base>/incidents`: retained snapshot, the authoritative state
    - `<base>/incident`: not retained; transition events `{"schema":1,"event":"new|updated|closed","incident":{...}}`
    - `<base>/availability`: retained `online`/`offline`
    - `<base>/health`: retained schema-v1 health object
  - **Snapshot:** `{schema:1, source, page_updated_at, fetched_at, incidents:[...]}`.
  - **Incident:** `id` (a stable hex hash), `agency{name,key,category,category_source}`, `received_at` (ISO 8601 with offset), `received_at_raw`, `type{raw,key,code?}`, `address_raw`, `address_clean`, `municipality{raw,name|null}`, `cross_streets_raw`, `cross_streets[]` and `status`.
  - **Restart semantics:** a producer restart re-seeds with **no** events. Consumers must bootstrap from the retained snapshot and reconcile periodically; events are only transitions.
- The existing code:
  - `config/models.py` `Agency.cad_names` (normalized, max 20 entries)
  - the M16 call agency snapshot (migration `0005`)
  - `alerts/mqtt.py` (aiomqtt usage, broker settings, `MqttTarget` reference patterns)
  - `api/routes/discovered_tones.py` (the "create from discovered" UX pattern to mirror for M17.4)
  - `recording/retention.py`
- The latest migration is `0006_alert_attempt_retry`, so yours is **`0007`**.

## Required
1. **Config (M17.2):** `AppConfig.cad_feeds: list[CadFeed]`, where `CadFeed` is `{id: Slug, name, type: Literal["icad2mqtt"], mqtt_target_id: Slug | None, host/port/tls/username/password (exactly one of target ref or host, mirroring MeshtasticTarget), base_topic (default "911/cad"), enabled, window_before_s (default 180, 0–3600), window_after_s (default 300, 0–3600)}`.
   - Validate dangling `mqtt_target_id`.
   - Secrets are masked like other targets, so the M18b secret round-trip protection must cover `cad_feeds` too. Add a test.
   - Add a CRUD API `/api/cad-feeds` following the existing `_crud` pattern.
2. **Subscriber (M17.2):** `cad/feed.py`, one asyncio task per enabled feed, owned by the supervisor lifecycle (start, stop, hot-apply on config change).
   - aiomqtt with reconnect and jittered backoff.
   - Subscribe to `<base>/incidents`, `<base>/incident` and `<base>/availability`.
   - **Untrusted input (M17.6):**
     - strict pydantic models with `extra="ignore"` but typed fields
     - `schema == 1` required
     - payload ≤ 1 MB (checked **before** JSON parse)
     - ≤ 500 incidents
     - every string bounded (e.g. 300 chars; ids `^[0-9a-f]{8,64}$`)
     - timestamps timezone-aware
   - Invalid messages increment a per-feed counter and are dropped. Never raise into the pipeline, and **never log incident fields** (addresses, types, cross streets): log only feed id, topic, reason and counts.
   - The snapshot is authoritative: on each snapshot, upsert every incident, and mark incidents absent from the snapshot as closed (`closed_at` = snapshot `fetched_at`). Events apply transitions in between.
   - Per-feed health: connected, availability, last message time, invalid count, active incidents. Expose it in `GET /api/admin/health` under a new `cad_feeds` section.
3. **Storage (M17.2):** migration `0007`.
   - Table `cad_incidents`: `feed_id`, `incident_id` (unique together), agency name/key/category, type raw/key/code, `address_clean`, `cross_streets` (JSON), municipality raw/name, `received_at` (UTC), status, `first_seen_at`, `last_seen_at`, `closed_at`.
   - Table `call_cad_incidents` (call id, feed id, incident id, `matched_at`, `delta_s`), unique per call+incident.
   - CAD rows follow the **call retention** policy: delete incidents older than the retention max age that are not linked to a retained call, plus linked rows when their call is deleted.
   - Include the upgrade → downgrade → upgrade test.
4. **Correlation (M17.3):** a `cad/correlate.py` service that is pure and clock-injected.
   - A call links to an incident when the call's matched tone set agency (from the M16 snapshot) has `Agency.cad_names` containing the incident's normalized agency name (`agency.key` compared case-insensitively against the normalized cad_names), **and** `received_at` is within `[call_start − window_before_s, call_start + window_after_s]`.
   - The nearest `|delta|` wins, with ties broken by the earlier `received_at`, and **at most one** incident per call per feed.
   - Run on call start (existing incidents) **and** on each new or updated incident (late arrival: link to calls within the window that have no link from that feed yet).
   - On a new link, publish a `CallEnriched` domain event.
   - Carry it on the WS event stream, the MQTT call topic (`.../call` with `event: call_enriched`), webhooks (`phase: call_enriched`, opt-in per webhook target via its existing `phases` list if present; otherwise document the choice), and the calls API (`GET /api/calls/{id}` gains `cad_incidents: [...]`).
   - **Never** put the address on the Meshtastic mesh unless the target template explicitly uses `{cad_address}`, and add `{cad_type}` and `{cad_address}` template fields per PLAN M18.2. Default templates stay address-free.
5. **Unmatched agencies (M17.4):** `GET /api/cad/unmatched-agencies` lists distinct incident agency names (key and display name) not in any `Agency.cad_names`, with count and last seen.
   - Add `POST /api/cad/unmatched-agencies/{key}/create-agency`, prefilled like discovered tones (name, `cad_names=[name]`, category mapped to the agency kind if one exists), with audit.
6. **Docs and security (M17.6):**
   - `docs/guide/cad.md`: setup with icad2mqtt, privacy note (addresses are stored and follow retention; use broker ACLs).
   - Threat model rows: untrusted MQTT input, address data at rest, no incident data in logs.
   - Regenerate the API client (`just gen-api`).

## Mandatory tests (write first; each separately named; map them to letters in the report)
- **A. Validation:**
  - an oversize payload (>1 MB) is rejected before parse
  - 501 incidents, a bad id, a naive timestamp, `schema: 2` and a 10 kB string are each rejected with the counter incremented
  - no exception escapes
  - a `caplog` assertion that no address or type string from those payloads appears in logs
- **B. Snapshot authority:** snapshot with A,B, then event `closed` B, then event `new` C, then a snapshot with A,C gives exactly A and C active and B closed. A producer restart (the same snapshot again, no events) changes nothing.
- **C. Correlation, pure:** in-window before and after, window edges inclusive, outside the window, the nearest wins, a tie goes to the earlier one, a different agency is not matched, and cad_names matching is case-insensitive.
- **D. Late arrival:** a call first, then a `new` incident 90 s later links, emits exactly one `CallEnriched`, and a duplicate `updated` event doesn't re-emit.
- **E. Migration 0007:** upgrade, downgrade, upgrade on a real SQLite file keeps call rows.
- **F. Retention:** unlinked old incidents are deleted, linked incidents are kept while their call exists, and are deleted with it.
- **G. API via ASGI:**
  - CRUD for `cad_feeds`, including 422 for a dangling target and 401/403
  - the secret round-trip (`[REDACTED]` PUT keeps the password)
  - `GET /api/calls/{id}` includes `cad_incidents`
  - unmatched agencies list and create-agency, with its audit row
- **H. Feed lifecycle:** a fake broker/client injected; reconnect after a disconnect with backoff (an injected sleep); stop cancels cleanly; disabling the feed via config hot-apply stops its task.
- **I. Meshtastic templates:** `{cad_type}` and `{cad_address}` render when an enriched payload is present. The default template has no address, proven by rendering with an enriched payload and asserting the address is absent.
- **J.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test name to its letter, with its first-run failing line and its passing line.
- `just check` (pytest before and after, with coverage lines for alerts, api and pipeline; add a `cad` package gate at ≥ 90 % in `check_package_coverage.py`), then `just e2e` on port 8826, then `just ci-local` up to `api-drift`.
- `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` code and pasting that result. Don't cite sources you didn't read.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark `docs/PROGRESS.md` M17.2–M17.4 and M17.6 `[~] ... — PENDING-REVIEW`.
- No new dependencies. Never weaken a gate. No `noqa`/`type: ignore` without a same-line justification.
- **Don't add conftest.py files in subdirectories** (mypy rejects duplicate module names); use `backend/tests/conftest.py`.
- Tests must never open real network sockets: zeroconf is guarded globally, and MQTT must be faked.
- **No real incident data** anywhere: fixtures use invented agencies and addresses only.
