# Brief: M19f — M19.5 config history, diff, rollback, export and import (backend + API)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-m19f` (branch `m19f`). **E2E port:** `TONEWATCH_E2E_PORT=8842`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Read first
- `PLAN.md` M19 intro and **M19.5** (~line 675).
- `config/store.py` (`ConfigStore.save_async`, the etag, atomic writes and the file lock).
- `api/routes/config.py`: **every** route that saves config (`PUT /api/config`, tone set, source, target and agency CRUD, tones.cfg import). Find the single save/apply path they share, or the several.
- `api/audit.py`: `record_audit`, `mask_secrets`, `restore_secrets`, `is_secret_key`, and the existing config before/after diffs.

## Required (backend and API only; the UI is a later slice)
Every mutating endpoint uses `write_auth`, writes an audit event, and never returns or logs a secret.

1. **History.**
   - Every successful config save, through **any** route, records one version. The history holds at most 100 versions, and older ones are pruned.
   - Store versions as files under `$TONEWATCH_DATA/config-history/` (no DB migration). Each version keeps an id, time, actor, source route and a SHA-256 of the canonical content. Write them atomically with owner-only permissions: **versions contain secrets at rest**, exactly like `config.yaml`. Document that.
   - `GET /api/admin/config/versions` lists versions, newest first (id, time, actor, route, hash; no content).
   - `GET /api/admin/config/versions/{id}` returns that version **masked**.
   - `GET /api/admin/config/versions/{id}/diff?against={id|current}` returns a structured diff (path, before, after) with secrets masked. A changed secret shows as `changed` and never shows its value.
2. **Rollback:** `POST /api/admin/config/versions/{id}/rollback` with `If-Match` (the current etag).
   - It goes through the **same validation and hot-apply path** as `PUT /api/config`, and it creates a new version, so history never rewrites itself.
   - A stale etag gives 412, and a version that no longer validates against the current model gives 422 with a readable reason.
3. **Export:** `GET /api/admin/config/export?format=yaml|json`.
   - Secrets are masked by default.
   - `include_secrets=true` also requires the confirmation `confirm=include-secrets` and bearer or session auth (**not** ingress). The response carries a warning header that the file holds secrets in plaintext, and it is audited.
   - Always sent with `Cache-Control: no-store` and `Content-Disposition: attachment`.
4. **Import:**
   - `POST /api/admin/config/import/preview` takes a YAML/JSON body, size-capped (reuse the existing body-limit pattern). It validates, and returns the structured diff against current, or 422 with readable errors. It applies nothing.
   - `POST /api/admin/config/import/apply` takes the same body plus `If-Match`, and applies through the normal path.
   - A masked `"[REDACTED]"` secret in an import restores the current secret, via `restore_secrets`. If there is no current secret to restore, it gives 422.
   - YAML must be parsed with a safe loader. Test that a `!!python/object` payload is rejected.

## Mandatory tests (write first; show each failing line)
- **A.** Saves through `PUT /api/config`, a tone-set create **and** a tones.cfg import each create exactly one version. There is a pruning test at 101 versions.
- **B.** Version files are owner-only on POSIX (skip on Windows with a reason). A version GET, a diff and a default export contain **no** fixture secret string; scan the whole serialized response.
- **C.** Rollback:
  - restores the old content and hot-applies it (the running config changes)
  - adds a version
  - a stale etag gives 412
  - an invalid old version gives 422 with the running config unchanged
- **D.** Export: masked by default; `include_secrets` without confirmation gives 422; ingress gives 403; `no-store` and the attachment header are set; and it is audited.
- **E.** Import preview applies nothing (the config file hash is unchanged). Apply with a stale etag gives 412. A `"[REDACTED]"` secret round-trips to the stored value. A YAML tag attack is rejected. An oversize body gives 413.
- **F.** An auth matrix for every new endpoint: no auth gives 401, and a cookie without CSRF gives 403 on writes. `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty.

## Gates and evidence (the report is rejected without it)
- A table mapping each test to its letter, with its **failing line before the implementation** and its passing line after. Paste them into your progress messages **as you go**, in case your turn is cut off.
- `just check` fully green, with every `check_package_coverage.py` line at least 1 % above its gate. Then `just ci-local` up to `api-drift` (run `just gen-api`; the only drift should be the uncommitted generated files). `git diff --stat`.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. You may mark M19.5 `[~] ... — PENDING-REVIEW` in `docs/PROGRESS.md`.
- No new dependencies. No subdirectory `conftest.py`. Never weaken a gate. No real incident data or real config values.
- Add a threat-model row with id **TM-048** (the parallel engineer M19g takes TM-049) and a `docs/guide/admin.md` section.
- **Parallel engineer M19g** works in `logging.py` and a new support route. Don't touch those. Keep any `api/app.py` edit to one router registration.
