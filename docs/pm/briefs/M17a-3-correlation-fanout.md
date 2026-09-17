# Brief: M17a-3 — correlation wiring, CallEnriched fan-out, calls API (finish M17a)

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0acf1-d8c3-7aa2-94a5-f423eddf22b9`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m17a` (your uncommitted M17a and M17a-2 work stays). **E2E port:** `TONEWATCH_E2E_PORT=8826`. `docs/pm/briefs/M17a-cad-backend.md` still applies in full.

## PM review of M17a-2: accepted
- The subscriber with jittered reconnect and hot-apply.
- The size check before parse (`MAX_PAYLOAD_BYTES`), and logs that carry only feed id, topic, reason and exception type.
- Snapshot authority, migration `0007` round-trip, retention, the admin health `cad_feeds` section, and tests A/B/E/F/H/J.
- `just check` passed with 599 tests, CAD at 93.71 %.

## This round (the last): M17a brief item 4, plus the tests left open
1. **Wire `cad/correlate.py` into the running system:**
   - on call start (match existing stored incidents)
   - on every `new`/`updated` incident persisted by the feed (late arrival: calls within the window with no link from that feed)
   - on snapshot upserts of incidents that are new to storage

   Persist links in `call_cad_incidents` (unique per call+incident, at most one per call per feed; nearest wins, ties go to the earlier `received_at`). Never run correlation for incidents whose agency matches no configured `cad_names`.
2. **`CallEnriched` fan-out** with a payload of the call id plus the incident fields (type, address_clean, cross_streets, municipality, received_at, agency), sent to:
   - the WS event stream (add the message to the WS models, then `just gen-api`)
   - MQTT call topic `tonewatch/<instance>/call` with `event: "call_enriched"`
   - webhooks: add `call_enriched` to the webhook `phases` literal (opt-in; the default phases don't include it), and document it
   - Meshtastic: only if the target's `phases` includes `call_enriched`. The **default template stays address-free**; `{cad_type}`/`{cad_address}` render only when the template uses them.
   - HA discovery event attributes: add `cad_type` and `cad_address` to the call event attributes only if the existing event payload path supports it cleanly; otherwise document it as a follow-up and **say so**.
3. **`GET /api/calls/{id}`** gains `cad_incidents: [...]`, and `GET /api/calls` gains a boolean `has_cad`.
4. Every delivery goes through the existing dispatcher, so retries, attempt rows and dedupe apply. A duplicate `updated` event must not re-emit `CallEnriched` for an existing link.

## Mandatory tests (write first; show each failing line)
- **D. Late arrival end to end** (real SQLite, fake feed input, a real dispatcher with fake senders): a call starts, then a `new` incident for a matching agency arrives 90 s later. Then:
  - exactly one link row
  - exactly one `CallEnriched` on the bus
  - one webhook send **only** for a target whose phases include `call_enriched`, and none for one without it
  - a following duplicate `updated` produces no second emit or send
- **D2. Call-start correlation:** the incident is stored first, then the call starts within the window, giving a link and an emit. An out-of-window call gives no link.
- **G** (finish it): `GET /api/calls/{id}` includes `cad_incidents`; `GET /api/calls` has `has_cad`.
- **I. Meshtastic:** the default template with an enriched payload has **no** address. A template with `{cad_type} {cad_address}` renders both, sanitized and byte-truncated. A target without `call_enriched` in phases sends nothing on enrichment.
- **MQTT:** the call-topic payload for `call_enriched` has the expected keys (a golden dict).
- **Privacy:** a `caplog` check across D shows no address or type string in logs.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its failing and passing lines.
- `just check` green (pytest count, coverage for cad, alerts, api and pipeline).
- `just e2e` on port 8826: paste the per-test lines.
- **`just ci-local`:** your last report said the "nested test runner exited early without traceback". Rerun it, paste the exact tail, and if it recurs, identify the cause (e.g. run `backend/scripts/run_pytest.py` directly and paste the output). Don't hand-wave it.
- `git diff --stat`.
- **If you run out of room, stop at a green `just check` and list exactly what's left.**

## Standing rules
- As in M17a. **Don't modify `api/audit.py`**: a separate secret-masking fix is queued.
