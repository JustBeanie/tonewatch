# Brief: M17a-2 — CAD feed subscriber, snapshot authority, retention and health (continue M17a)

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0acf1-d8c3-7aa2-94a5-f423eddf22b9`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m17a` (your existing uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8826`. Environment and git rules are the same as M17a.

## Status
Your M17a report was an honest partial: config, models, migration `0007`, pure correlation, API and tests A/C/G exist, `just check` isn't green (CAD coverage gate), and D–J are missing. The remaining work is split into two rounds. **This round covers only the items below;** correlation fan-out comes next round. **Everything in `docs/pm/briefs/M17a-cad-backend.md` still applies.**

## This round (do all of it)
1. **`cad/feed.py` subscriber** (M17a brief item 2).
   - One task per enabled feed, owned by the supervisor start/stop, **hot-applied** on config change: add, remove or disable a feed without restarting others.
   - aiomqtt through an injectable client factory and injectable sleep.
   - Jittered reconnect backoff.
   - Subscribe to `<base>/incidents`, `<base>/incident` and `<base>/availability`.
   - Size check before parse, strict validation, a per-feed invalid counter, and never raise or log incident fields.
2. **Snapshot authority:** persist snapshots and events to `cad_incidents` per the M17a brief.
   - Incidents absent from a snapshot are closed at its `fetched_at`.
   - A repeated identical snapshot is a no-op: no row churn, and `last_seen_at` may update.
3. **Health:** per-feed `connected`, `availability`, `last_message_at`, `invalid_total`, `active_incidents` in `GET /api/admin/health` under `cad_feeds`. Update that endpoint's exact key-set snapshot test.
4. **Retention:** extend `recording/retention.py` (or its job) per M17a brief item 3.
5. **Coverage:** make `just check` green, including your new `cad` package gate at ≥ 90 %, **with tests, not exclusions.**

## Mandatory tests this round (write each first; show its failing line)
- **A** (finish it): add the `caplog` assertion that no address or type string from rejected payloads appears in logs, if it's missing.
- **B:** snapshot authority (A,B, then close B, then new C, then snapshot A,C gives A and C active, B closed), and a restart re-seed with no change.
- **E:** migration `0007` upgrade, downgrade, upgrade on a real SQLite file keeps call rows.
- **F:** retention (unlinked old incidents deleted; linked ones kept with their call, deleted with it).
- **H:** feed lifecycle with a fake client (reconnect after disconnect using injected sleep; stop cancels; disabling a feed by hot-apply stops only its task).
- **Health:** the `cad_feeds` section reflects a fake feed's state.
- **J:** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Evidence (the report is rejected without it)
- A table mapping each test to its letter, with its first failing line and its passing line.
- `just check` green: paste the pytest count and the coverage lines for `cad`, alerts, api and pipeline.
- `git diff --stat`.
- **If you run out of room, stop at a green `just check` with a subset done**, and list exactly what's left. Don't leave the gate red.

## Standing rules
- As in M17a: no new dependencies, no real incident data, no subdirectory `conftest.py`, and no real sockets in tests. Never edit `docs/pm/**` or `PLAN.md`. Never write git state.
