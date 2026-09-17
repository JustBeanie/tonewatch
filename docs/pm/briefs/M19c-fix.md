# Brief: M19c-fix — the host e2e found a backend masking bug, a raw health page, and a bad locator

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0b012-dac4-7a22-92de-627308cf4d36`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19c` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8836`. `docs/pm/briefs/M19c-admin-ui.md` still applies.

## PM host verification
Your sandbox had no Playwright browsers, so the PM ran `just e2e` on the host. **The 8 existing specs passed, but your 3 new specs failed.** Screenshots and error contexts are in `C:\Users\beanie\AppData\Local\Temp\claude\C--Users-beanie-Documents-claude\84fbbdaf-f9a6-4447-a9f1-4fd699a53ece\scratchpad\m19c-e2e\`.

1. **Admin alerts save fails, because of a real backend bug** (from the secret-masking change `1fd0965`).
   - The page shows `redacted placeholder has no stored value for password`.
   - Cause: `api/audit.py` `mask_secrets` replaces a secret key's value with `"[REDACTED]"` **even when the stored value is `None` or `""`**. The e2e config has MQTT/Meshtastic targets with no password, so `GET /api/config` returns `password: "[REDACTED]"`, the PUT sends it back, and `restore_secrets` correctly refuses it.
   - **Fix in `api/audit.py`:** `mask_secrets` must leave `None` and `""` unchanged (only non-empty secrets are masked). Keep `restore_secrets` strict.
   - **Backend tests** (write first, show them failing):
     - `mask_secrets({"password": None})` keeps `None`, and `""` stays `""`
     - an ASGI GET→PUT of the full config where a target has **no** password gives 200
     - a target **with** a password still round-trips, keeping the secret
2. **The health page renders raw data.** Fix the formatting in the UI (no backend change unless a field is actually wrong).
   - **Numbers:**
     - realtime factor to 1 decimal (`2960.6×`, or `>1000×` above 1000)
     - bytes human-readable (`21.7 KB`, `122.3 GB`)
     - forecast days rounded (`1,493 days`, or `no growth`)
     - uptime as `1h 02m 03s`
     - DB size human-readable
   - **Layout:** each labelled value is separated (a definition list or table). No run-on text like `Fixture radioRealtime factor`.
   - **Event bus:** `admin/health.py` `event_bus_health` returns a **list** of subscriber entries, but `Health.tsx` (~lines 92–106) reads it as an object, so everything shows "—". Render the list (a name or index, depth, dropped, lag) and show totals.
   - **Outputs:** `MQTT: false` should read `MQTT disconnected`, or `—` for non-MQTT targets.
   - **History:** feed health history renders as a compact row of healthy/unhealthy markers with an accessible text summary, or "no history".
   - Vitest for each formatter (unit tests for `formatBytes`, `formatDuration`, `formatFactor`), plus a render test using a fixture shaped **exactly** like the real `HealthResponse`. Copy the shape from `backend/src/tonewatch/admin/health.py`/`api/routes/admin.py`; don't guess it.
3. **E2E fixes:**
   - The health spec waits for `fixture-radio`, but the page shows the source **name** (`Fixture radio`). Assert on the displayed name, or add a `data-testid` per source id.
   - The delivery log spec's regex matches the `<option>` elements (a strict-mode violation). Scope it to the table or empty-state region (e.g. `getByRole("table")` or a `data-testid`).

## Evidence (the report is rejected without it)
- The backend test failing line (pre-fix) and passing line, and each new Vitest test with its failing and passing lines.
- **E2E:** your sandbox can't run browsers, so say so again; the PM reruns on the host. Still run `just check` fully green (pytest, Vitest, web coverage **≥ 81 %** branches for margin) and `just ci-local` up to `api-drift`.
- `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- As in M19c. You **may** edit `backend/src/tonewatch/api/audit.py` for item 1 only.
- **Parallel engineers:** M19d is in `api/auth.py`, `api/routes/auth.py` and credentials; M19e is in retention, storage and metrics. Don't touch those.
