# Brief: M19b — admin alerts (PLAN M19.2, backend only)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19b` (branch `m19b`, from `origin/main`, which has M19a admin health). **E2E port:** `TONEWATCH_E2E_PORT=8810` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.
**🚨 pytest temp dirs:** if you need `--basetemp`, point it **outside the repo** (`$env:TEMP\tonewatch-pytest`). A `.pytest-tmp` inside the worktree breaks the PM's host gate with a permission error.
**Git:** never write git state (no fetch, stash, merge, add, commit). Read-only diff/status/show is fine.

## Read first
- `PLAN.md` M19 intro and **M19.2** (the spec).
- `backend/src/tonewatch/admin/health.py`: `RealtimeFactor`, `ChannelHealth`, `OutputHealth`, `storage_forecast`, `event_bus_health`, `StorageScanner`, `bounded_error`. **Reuse these**; don't build a second metrics path.
- `api/routes/admin.py` for how health is assembled, `alerts/dispatcher.py` for sending, `config/models.py` for the target union, and `events.py` for the event types.

## Scope
**In:** the admin-alert engine, its config, and delivery through existing alert targets.
**Out:** UI, Prometheus (M19.10), and any change to page-alert behaviour. Detection and paging must be untouched.

## Required
1. **Config** `AdminAlertsConfig` on `AppConfig` (field `admin_alerts`), **disabled by default**, validated with bounds and `extra="forbid"`:
   - `enabled: bool = False`
   - `targets: list[str] = []` (alert-target ids; validated to exist, like tone-set targets)
   - `feed_unhealthy_min: float = 5` (1–1440)
   - `disk_used_pct: float = 90` (50–99)
   - `disk_forecast_days: float = 7` (1–365)
   - `target_failures: int = 5` (2–100)
   - `squelch_stuck_open: bool = True`
   - `realtime_factor_min: float = 1.5` (1.0–10) with `realtime_factor_min_s: float = 300` (30–3600)
   - `min_interval_s: float = 300` (60–86400) per condition key, and `max_per_hour: int = 6` (1–100) overall
   - Existing configs without the section must load unchanged (test a pre-M19b YAML).
   - Every `AppConfig` rebuild already goes through `replace_config`; **don't** add a field-by-field rebuild. Add an `admin_alerts` case to the existing `test_all_config_mutation_paths_preserve_untouched_fields` parametrization.
2. **Engine** `admin/alerts.py`, pure and clock-injected where possible:
   - **Condition keys:** `feed_unhealthy:<source_id>`, `disk_used`, `disk_forecast`, `target_failures:<target_id>`, `squelch_stuck_open:<source_id>`, `realtime_factor:<source_id>`.
   - Each condition is **edge-triggered**: it fires once when it becomes true and stays latched; when it clears, it sends one **resolved** follow-up. Never repeat the firing message while latched, except as the re-notify rule below allows.
   - **Re-notify:** while latched, at most one reminder per `min_interval_s`, capped by `max_per_hour` across all conditions. Drops are counted, never silent (log at warning with the condition key and a counter).
   - **Dedupe:** the same condition key can't have two in-flight notifications.
   - **Hysteresis:** a condition must hold for its duration (`feed_unhealthy_min`, `realtime_factor_min_s`) before firing; a momentary blip must not fire. Clearing is immediate.
3. **Payload and delivery.**
   - Build the payload from the existing health model. Include `kind: "admin"`, `condition`, `state: "firing"|"resolved"`, `severity`, `since`, `detail` (a short human string), and the relevant numbers.
   - **`kind: "admin"` must be unmistakable:** MQTT publishes to an admin topic, not the call topic; HA discovery must not create page-like `event` entities for it; webhook and script payloads carry `kind`.
   - Reuse `AlertDispatcher`'s sender path for each target type. **Never** reuse the call-dedupe or coalescing paths meant for pages, and never write `AlertAttempt` rows tied to a fake `call_id` (use a null/`None` call reference or a separate table field; state clearly in the report which you chose and why).
   - Secrets never appear in payloads or logs; error strings go through `bounded_error`.
4. **Wiring:** evaluate on a timer inside the existing supervisor or API lifespan (no new process), default every 30 s, cancelled cleanly on shutdown and on `reload`. Evaluation must never block the event loop (reuse the cached `StorageScanner`).
5. **Docs:** an admin-alerts section in `docs/guide/admin.md` (conditions, defaults, rate limits, resolved follow-ups, the `admin` marking), PROGRESS M19.2 marked PENDING-REVIEW, and ASVS/threat-model rows following the existing conventions (quote-all CSV, LF, re-derived anchors).

## Mandatory tests (the report maps each test name to its letter)
- **A.** Config: defaults, bounds rejected through `POST /api/config` or the config store with 422 naming the field, an unknown target id rejected, and a pre-M19b YAML loading unchanged.
- **B.** Feed unhealthy: unhealthy for less than the threshold does **not** fire; past it fires exactly once; recovery sends exactly one `resolved`.
- **C.** Disk: `disk_used_pct` crossing fires; a forecast under `disk_forecast_days` fires with its own key; both clear.
- **D.** Target failures: N consecutive failures fire once; a success clears with a `resolved`.
- **E.** Squelch stuck open fires from the existing `SquelchHealthChanged` flag and clears with it.
- **F.** Realtime factor below the threshold for the duration fires; a brief dip does not.
- **G.** Rate limiting: while latched, reminders respect `min_interval_s`; the hourly cap drops extras, and the drop is counted and logged.
- **H.** Dedupe: two evaluations in the same tick send one notification.
- **I.** Payload: `kind: "admin"` present for every target type; the MQTT topic is the admin topic, not the call topic; no secret appears anywhere (inject a webhook URL with credentials and an MQTT password).
- **J.** Pages are unaffected: with admin alerts enabled and firing, a normal `ToneDetected` still produces the exact same call payload and attempts as with the feature off (assert equality of the recorded payloads).
- **K.** Lifecycle: the timer starts, is cancelled on shutdown without warnings, and a `reload` that disables the feature stops evaluation and clears latches.
- **L.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Evidence (the report is rejected without this)
- A table: test name → letter (A–L).
- For each required item 1–4, the failing test line first (test-first), the passing line, and a diff excerpt with file:line.
- The pytest count at your base (`just test` first) and after; the coverage lines for the new modules (gates must pass unchanged).
- `just check`, `just e2e` (port 8810; if the launcher hangs after the 4 specs pass, paste that line and continue), `just ci-local` up to api-drift, plus `git diff --stat -- web/src/api`.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` code and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. Never weaken a gate or coverage threshold.
- No new dependencies. No real radio data.
- Never write git state. Don't describe work you haven't done.
