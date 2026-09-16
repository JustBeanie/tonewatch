# Brief: UI1 — web UI for live listen and squelch (PLAN M14.4 + M15.5, plus M15.7 diagnostics display)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-ui1` (branch `ui1`, from `origin/main`, which has M14a/M15a/M15b/M16a/M18a). **E2E port:** `TONEWATCH_E2E_PORT=8809` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest errors with `PermissionError ... pytest-of-Beanie`, add `--basetemp backend/.pytest-tmp` (never commit it).
**Git:** never write git state (no fetch, stash, merge, add, commit). Read-only diff/status/show is fine.

## Scope
**In:** the web UI only, for features whose backends already exist.
- **M14.4 live listen:** `POST /api/sources/{id}/live-url`, `GET /api/sources/{id}/live.mp3`, `live_listeners` in source status, `LiveListenersChanged` over WS.
- **M15.5 squelch controls:** `SourceBase.squelch` (modes `off|level|noise_floor|auto`), the level meter with open/close lines and an open/closed lamp, "Set from noise floor".
- **M15.7 diagnostics display:** `squelch_mode_effective`, `noise_floor_dbfs`, `open_dbfs_effective`, `close_dbfs_effective`, `calibrating`, `stuck_open`, `chatter`, `transitions_per_min`, plus the calibrate endpoint `POST /api/sources/{id}/squelch/calibrate`.

**Out:** agencies/map UI (M16.4), Meshtastic form (M18.4), admin pages (M19), and any backend behaviour change. If a backend gap blocks you, write it in the report; don't redesign the API.

## Read first
- `web/src/features/sources/Sources.tsx` (154 lines), `dashboard/Dashboard.tsx` (81), `spectrum/Spectrum.tsx` (94) for the house patterns.
- `web/src/api/client.ts`, `src/api/generated/`, `src/lib/ws.ts`, `src/lib/urls.ts` (ingress-aware base path).
- `web/tests/*.test.tsx` for the Vitest/Testing Library style, and `web/e2e/tonewatch.spec.ts` for Playwright.
- The guides `docs/guide/listen-live.md` and `docs/guide/tuning.md`.

## Required
1. **Listen live (M14.4).**
   - On each source card and the dashboard, a **Listen live** control, shown only when the source has `live_stream_enabled` and the feature is enabled; otherwise show a disabled control with the reason.
   - Clicking mints a URL via `POST /api/sources/{id}/live-url` and plays it in an `<audio controls>` element. Stop releases the element (`src=""`, `load()`), so the listener slot frees.
   - Show the **listener count** from source status, live-updated by `LiveListenersChanged` over WS.
   - **Copy player URL** copies the signed URL and shows its **expiry** as a local time plus a relative "expires in N min". Never log the URL or put it in the page title. Use `navigator.clipboard` with a documented fallback.
   - Show the **rebroadcast disclaimer** beside the settings toggle (text from `docs/guide/listen-live.md`).
   - Handle 503 (caps reached) with a clear message and no console error.
2. **Squelch controls (M15.5).**
   - On the source form: mode select (`off|level|noise_floor|auto`), and fields per mode. Level shows `open_dbfs`/`close_dbfs`, `attack_ms`, `hang_ms`; noise floor adds `floor_margin_db`; auto shows `auto_window_s`, `auto_min_samples_s`, `auto_k`, `min_margin_db`, `max_margin_db`, `stuck_open_s`, `max_transitions_per_min`. Irrelevant fields hide, and the backend's bounds are mirrored as input constraints with inline validation errors (422 details are surfaced, never swallowed).
   - The **live level meter** draws the **effective** open and close lines and an **open/closed lamp**, driven by the WS level messages. In `off` mode the lamp reads "disabled" and no lines are drawn.
   - **"Set from noise floor"** calls the calibrate endpoint (default 10 s, allowed 5–120), shows progress, then fills `open_dbfs`/`close_dbfs` from the suggestion **without saving**. The user still presses Save. Surface 409 (source not running) and 429 (already calibrating) as inline messages.
3. **Diagnostics (M15.7).** On the source card show effective thresholds, noise floor and `transitions_per_min`, plus badges for `calibrating`, `stuck_open` and `chatter`, each with a tooltip explaining it. All are hidden when the value is `null`.
4. **Quality bar.** TypeScript strict, ESLint and Prettier clean, no `any`, no `eslint-disable` without a same-line justification. Follow `jsx-a11y`: every control has an accessible name, the lamp and badges are not colour-only (add text or an icon), and the meter has `role="img"` with an `aria-label` describing the state.
5. **Generated client:** if you touch backend schemas, stop and report instead. Run `just gen-api` only to confirm there is no drift.

## Mandatory tests (the report maps each test name to its letter)
**Vitest (`web/tests/ui1.test.tsx` or similar), with MSW or fetch mocks in the existing style:**
- **A.** Listen live mints a URL, sets the audio `src`, and stop clears it.
- **B.** The listener count renders from status and updates on a `LiveListenersChanged` WS message.
- **C.** Copy URL writes to the clipboard and renders the expiry; the URL never appears in a `console` call (spy on `console.log`/`info`/`warn`/`error`).
- **D.** A 503 on mint renders the cap message, and no unhandled rejection occurs.
- **E.** The mode select shows and hides the right fields for all four modes.
- **F.** Out-of-range input shows an inline error and the Save button doesn't fire a request; a 422 response renders the field-level message.
- **G.** The meter draws open/close lines at the effective thresholds and the lamp reflects `squelch_open`; in `off` mode the lamp reads "disabled".
- **H.** "Set from noise floor" fills both fields from the suggestion without saving; 409 and 429 render inline messages.
- **I.** Diagnostics badges appear only when non-null, and the tooltip text is present.
- **J.** Accessibility: every new interactive control has an accessible name (`getByRole` queries only, no `container.querySelector`).

**Playwright (extend `web/e2e/tonewatch.spec.ts`), against the compose/file-source stack already used by `just e2e`:**
- **K.** With live streaming enabled for the file source, click Listen live, assert the audio element gets a `src` and the listener count becomes 1, then stop and assert it returns to 0.
- Keep the existing specs green.

## Evidence (the report is rejected without this)
- A table: test name → letter (A–K).
- For each required item 1–3, the first failing line of its test (test-first), the passing line, and a diff excerpt with file:line.
- `just check` (paste the Vitest summary and coverage; web coverage must stay ≥ 80 %), `just e2e` on port 8809 (if the launcher hangs after the specs pass, paste that line and continue), and `just ci-local` up to api-drift with `git diff --stat -- web/src/api`.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` code and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. Never weaken a gate or a coverage threshold.
- No new runtime dependencies without saying why in the report; prefer what's already in `package.json`.
- No real radio data or private fixtures. Invented names only.
- Never write git state. Don't describe work you haven't done.
