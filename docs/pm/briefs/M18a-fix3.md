# Brief: M18a-fix3 — Meshtastic: fix your dispatcher regression, then finish the mandatory tests

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a1c3-42b9-7691-ab5a-f764e7d4bf78`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m18a`. **E2E port:** `TONEWATCH_E2E_PORT=8806` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.
**Git:** never write git state (no fetch, stash, merge, add or commit). Read-only diff/show is fine.

## Verdict on M18a-fix2: FAIL (regression + tests)
**Kept, PM verified in code:**
- The target is re-checked after the coalesce sleep (`dispatcher.py:334-338`).
- `_mesh_sent` is marked before the awaited send (`:351`).
- Mesh state is pruned on call close (`:330`).
- The `test_target` timeout uses the target's own timeout (`:487`).
- New tests: follow-up after the window, follow-up limiter recorded once, pruning, reload cancel, payload URLs.

### 1. The two app-wiring failures are YOUR regression, not "existing Windows failures"
The PM ran the same two tests on the host:

```text
main checkout f57f051 (no M18a changes):
  2 passed, 12 deselected in 8.17s
tonewatch-m18a worktree (your changes):
  FAILED tests/integration/test_app_wiring.py::test_webhook_alert_fires_for_real_recorded_call
  FAILED tests/integration/test_app_wiring.py::test_recording_ready_alert_waits_for_persisted_row_without_polling
  2 failed ... TimeoutError (asyncio.timeouts) — webhook POSTs received HTTP 200 but the test's wait never completed
```

- **Diagnose from your diff**, which touched the dispatcher's `handle`/`_dispatch`/close/prune/`_seen`/`force` paths. The webhook gets its POSTs, so suspect the step **after** delivery: attempt-row recording, `recording_ready` handling after a call closes (pruning removing state that `recording_ready` still needs?), dedupe keys, or an exception swallowed by `gather(return_exceptions=True)`.
- **Fix the product code.** Never loosen these tests, add waits, or skip them.
- **Evidence:**
  - the root cause in 2–3 sentences with file:line
  - the failing line before the fix and the passing line after
  - a regression unit test that pins the root cause and fails without the fix
- **Note:** if pytest errors with `PermissionError ... pytest-of-Beanie`, pass `--basetemp <a dir inside the worktree, e.g. backend/.pytest-tmp>`. It is gitignored or must stay untracked; don't commit it.

### 2. Mandatory tests still missing from M18a-fix2
Numbers refer to that brief; each is required, and the report maps test name to number.
- **2 (race):** a sender blocked on an `asyncio.Event`; a tone set arriving mid-send goes out as exactly one follow-up and is never lost.
- **5 (route contract):** replace `test_alert_target_test_route_marks_synthetic_delivery` so the route response is exactly `{ok, error}`, with no `call_id`.
- **7 (embedded broker):** use the **existing** broker fixture in `tests/integration/test_mqtt_broker.py`, driving `AlertDispatcher.handle(ToneDetected(...))`. Assert topic `msh/US/2/json/mqtt/`, QoS 1, retain false and the exact JSON envelope.
- **8 (rate limit rows):** with a real temp SQLite session factory, `min_interval_s` and `max_per_hour` each yield exactly one `AlertAttempt` row with error `rate_limited`.
- **9 (phases):**
  - `["pre_alert"]` sends nothing for `recording_ready`/`closed`.
  - `["recording_ready"]` sends on that phase only, with no coalescing delay (the injected sleep is never called).
- **10 (template reload):** a template changed via `reload` is used for the next call.
- **11 (timezone):** a fixed UTC instant renders in `America/New_York`. With `timezone` unset, `TZ=Europe/Berlin` (monkeypatch) is honoured; with neither set, UTC.
- **12 (agency):** agency absent, `agency=None`, and a stacked call spanning two agencies (dict present is already covered). No output contains `{`, `[` or `'id'`.
- **13 (`test_target` real dispatcher):** real `AlertDispatcher` + fake sender + real temp DB. Exactly one send, zero `AlertAttempt` rows, one `alert_target_test` audit row; a failing sender's error surfaced; a slow sender times out at the target timeout.
- **14 (secrets):** `GET /api/alert-targets` and `/api/alert-targets/{id}` mask the Meshtastic `password`. Audit before/after diffs for create and update never contain the plaintext.

## Gates and evidence
- **`just check` must be GREEN.** A report with failing tests is rejected; fix the product, never the test.
- Paste: pytest and vitest summary lines; the pytest count before (425) and after; `just e2e` (port 8806); `just ci-local` up to api-drift; `git diff --stat -- web/src/api`.
- `git diff origin/main -- backend/tests/unit/test_s4_security.py`: only additions are allowed if item 14 needs them. Prefer a new test file and keep that diff empty.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` code and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`.
- Never weaken a gate. No new `noqa`/`type: ignore` without a same-line justification.
- No new dependencies, and nothing from the GPL `meshtastic` package or its protobufs. Invented node ids and names only.
- Don't describe work you haven't done.
