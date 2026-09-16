# Brief: M18b — M18.4 Meshtastic alert-target API and UI (byte-count preview, send test)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m18b` (branch `m18b`). **E2E port:** `TONEWATCH_E2E_PORT=8820` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo (e.g. `$env:TEMP\tonewatch-m18b-pytest`).
**Git:** never write git state.

## Context (read first)
- `PLAN.md` M18 (lines ~620–650).
- `docs/decisions/0012-meshtastic-transport.md`.
- `backend/src/tonewatch/config/models.py` `MeshtasticTarget` (~line 383).
- `backend/src/tonewatch/alerts/meshtastic.py`: `render_message`, `truncate_utf8`, `sanitize`.
- `backend/src/tonewatch/api/routes/config.py`: the generic `_crud` routes and `POST /alert-targets/{id}/test`.
- `backend/src/tonewatch/api/deps.py` `_dump` → `api/audit.py` `mask_secrets`, which replaces any key containing a secret word with `"[REDACTED]"`.
- `web/src/features/alerts/Alerts.tsx`: currently an 88-line stub.

## Bugs already present (fix them, each with a failing test first)
1. **Wrong "Send test" call.** `Alerts.tsx` "Send test" calls `request("tonesets/t1/test")` for **every** target. That hardcoded tone set is wrong; it must call `POST alert-targets/{id}/test` for that target and show the returned `ok`/error.
2. **Secret round-trip corruption.** `GET /api/alert-targets` masks `password`/`secret` as `"[REDACTED]"`. If the UI (or any client) PUTs that object back, the stored password becomes the literal `"[REDACTED]"`.
   - Make `PUT /alert-targets/{id}` keep the existing stored value for a secret field when the incoming value is `"[REDACTED]"` or the key is omitted.
   - An explicit `null` must still clear the secret.
   - Apply this generically to every alert-target type (mqtt, webhook, meshtastic), not only Meshtastic.

## Required
1. **Preview endpoint** `POST /api/alert-targets/meshtastic/preview` (`write_auth`, since it takes a config body; register it **before** the `{item_id}` routes so it isn't shadowed).
   - Body: a `MeshtasticTarget`-shaped object (validated; 422 on invalid) plus optional `sample` overrides.
   - It uses the **same** `render_message` the sender uses, with a fixed synthetic sample payload (agency short name, tone set name, fixed `detected_at`, source id, `test: true`).
   - It returns `{text, bytes, max_bytes, truncated}`.
   - **No MQTT connection and no persistence.** The response never contains broker credentials.
   - Add it to the OpenAPI schema and run `just gen-api`.
2. **UI in `Alerts.tsx`** (split into components under `web/src/features/alerts/` if it grows past ~200 lines):
   - Add `meshtastic` to the type select. When selected, show fields for: broker host/port/tls/username/password, **or** an existing MQTT target picker (exactly one, mirroring the model validator), `root_topic`, `gateway_node_id`, `channel_index` 0–7, `destination`, `template`, `max_bytes`, `phases`, `min_interval_s`, `max_per_hour`, `timezone`.
   - **Live byte-count preview:** debounce ~300 ms, call the preview endpoint, and show the rendered text and `N / max_bytes bytes`, with a visible "truncated" warning.
     - Never compute the byte count client-side as the source of truth; the server is authoritative.
     - Show preview errors (422) inline.
   - **Public channel acknowledgement:** when `channel_index == 0`, show a warning and require the `acknowledge_public_channel` checkbox before Save is enabled. The server validator already enforces it; show the server 422 if it's hit.
   - Show the note that mesh messages are readable by anyone with the channel key, and that URLs never go on the mesh.
   - Password inputs are write-only: an empty value on edit means "keep". Never render a stored secret.
   - Keep the existing mqtt/webhook/script behaviour working.
3. **Carry-over nit from M18a:** the M18a dispatcher race test reuses one tone set for both calls. Change it to use two distinct tone sets so it proves per-target limiting across different pages. Show before/after.

## Mandatory tests (write first; each a separately named test)
- **A.** Preview returns the exact text and byte count for a template with multi-byte characters (e.g. `é`, emoji), including a case where truncation lands mid-code-point. Assert `bytes <= max_bytes` and that the text decodes cleanly.
- **B.** Preview gives 422 on an invalid target (bad `gateway_node_id`, `channel_index` 8, both host and `mqtt_target_id`), 401 without auth, and 403 for a cookie session without CSRF.
- **C.** Preview never opens a connection: monkeypatch the MQTT client constructor to raise, and the preview still succeeds. The response has no `password` key or value.
- **D.** Secret round-trip for **each** of mqtt, webhook and meshtastic: create with a secret, GET (masked), PUT the GET body back unchanged, then assert the stored config still holds the original secret. PUT with an explicit `null` clears it.
- **E.** The test-send endpoint for a Meshtastic target through ASGI with a fake sender publishes once, with the `TEST ` prefix, and records an audit row.
- **F. Vitest:**
  - Selecting meshtastic renders the fields.
  - Typing a template triggers **one** debounced preview call and shows `N / 200 bytes`.
  - The truncated warning appears.
  - Save stays disabled on channel 0 until acknowledged.
  - "Send test" calls `alert-targets/<id>/test`, not `tonesets/...`.
- **G. Playwright** (extend `web/e2e/tonewatch.spec.ts`): create a Meshtastic target via the form using an existing MQTT target reference, see the preview byte count, save, and see it listed. Don't require a real broker.
- **H.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping test name → letter, with each test's first-run result (failing line, or "passed immediately") and its passing line.
- `just check` (pytest count before and after, and coverage lines for alerts and api), then `just e2e` on port 8820, then `just ci-local` up to `api-drift`. Paste `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` code and pasting that result. Don't describe work you haven't done, and don't cite sources you didn't read.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark `docs/PROGRESS.md` M18.4 as `[~] ... — PENDING-REVIEW`.
- No new dependencies. Never weaken a gate or coverage threshold. No new `noqa`/`type: ignore`/`eslint-disable` without a same-line justification.
- No URLs or tokens in anything that could reach the mesh.
