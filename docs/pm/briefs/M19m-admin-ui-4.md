# Brief: M19m — admin web UI for M19.6 backup and M19.12 replay (the last M19 UI slice)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19m` (branch `m19m`). **E2E port:** `TONEWATCH_E2E_PORT=8858` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19.6 and M19.12. `docs/guide/admin.md` sections on backup/restore and replay, including the tone-trimmed recording limitation.
- **The backend that exists** (read the route files for exact shapes; don't guess):
  - `api/routes/backup.py`: `POST /api/admin/backup` with `{include_recordings, include_credentials}` streams a `.tar.gz`. It gives 409 when maintenance is busy and 429 on the rate limit; ingress plus `include_credentials` gives 403. Restore is **CLI only**: `tonewatch backup restore FILE [--dry-run]` while the server is stopped.
  - `api/routes/replay.py`: `POST /api/admin/replay/uploads` (a WAV; 413/422) returns an upload id. `POST /api/admin/replay` with `{draft, calls: {last_n}, uploads: [ids]}` returns items (`classification`, `recorded`, `draft` detections, `reason`), a `summary`, `audio_seconds`, `audio_cap_seconds` and `limitations`. It gives 429 when a replay is running and 404 for an expired upload.
- The existing admin pages (`web/src/features/admin/`), the shared helpers (`shared.ts`, `download.ts`, the Audit diff view), the tone-set editor in `web/src/features/tonesets/` (for building a draft), `Shell.tsx`/`router.tsx`, and the readable-422 helper.

## Required (web only; no backend changes)
1. **Backup page** (`/admin/backup`):
   - "Include recordings" and "Include credentials" checkboxes, with a plain warning that the archive contains config secrets and should be stored like a password. Credentials add the API token and UI password. **Hide "Include credentials" through ingress.**
   - Download via `download.ts`, with the progress or "preparing…" state disabled while in flight.
   - Readable 409, 429 and 403.
   - A **restore** section that only explains the CLI steps: stop the server, `tonewatch backup restore FILE --dry-run`, then run without `--dry-run`, and what is moved aside into `pre-restore-*`. Put the commands in copyable code blocks. **No restore button.**
2. **Replay page** (`/admin/replay`):
   - **Build the draft** from the current config: load `GET /api/config`, then let the user edit tone sets in a compact editor (frequencies, tolerance and durations per tone, and enable/disable). Reuse the tone-set form components if they fit; otherwise write a minimal editor. Also allow "paste draft YAML/JSON" as an advanced option.
   - **Sources:** "last N calls" (1–50) and/or uploaded WAVs (multi-upload through the uploads endpoint, each with its upload id and a remove button).
   - **Run:** show the results table (item, recorded, draft detections with times, and a classification badge: would detect / would miss / new detection / unchanged / skipped with its reason), summary counts, and audio seconds against the cap.
   - Show `limitations` prominently: call replay checks voice false positives, and uploads test detection.
   - Readable 422 (a draft validation error with its field path), 429, 404 (expired upload: offer to re-upload) and 413.
   - The draft is **never saved** from this page. Add an explicit "Open in tone sets to save" link instead.
3. Add both pages to the Admin nav group.

## Mandatory tests (write first; show each failing line)
- **A. Backup:**
  - the POST body matches the checkboxes
  - the credentials checkbox is hidden through ingress
  - 409, 429 and 403 show their messages
  - the button is disabled while in flight
  - the restore section contains the CLI commands and **no** restore request is ever made (spy on fetch)
- **B. Replay:**
  - the draft built from a fixture config plus an edited frequency is sent exactly, with no `[REDACTED]` introduced for untouched secrets
  - an upload returns its id and it's included in the run body
  - the results render each classification with a text label (not colour alone)
  - `limitations` render
  - a 422 renders its field path
  - a 404 on an expired upload offers re-upload
  - a 429 renders
  - no request ever hits a config save endpoint (spy: no `PUT /api/config`)
  - a `<b>` in any reason renders as text
- **C. Playwright** (extend `web/e2e/tonewatch.spec.ts`):
  - open Backup and download an archive, asserting a `.tar.gz` download event
  - open Replay, run "last 1 call" against the unchanged draft, and see a result or the empty-calls state
  - no external requests
- **D.** `git diff origin/main -- backend/` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` (Vitest count; web branch coverage **≥ 81 %**). Also run `just e2e` on port 8858 if your sandbox has browsers; **if it doesn't, say so**, and the PM runs it on the host. Then `just ci-local` through `api-drift`. `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result. Don't report green unless you ran the full command after your last edit.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark the UI parts of M19.6 and M19.12 `[~] ... — PENDING-REVIEW`.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate. No real incident data.
- In Playwright, a `<select>`'s `<option>` is never "visible"; use `toBeAttached()` or `selectOption`.
- **Parallel engineer LEAK1** is in backend tests. Stay in `web/**`.
