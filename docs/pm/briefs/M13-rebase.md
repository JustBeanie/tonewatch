# Brief: M13-rebase — resolve conflicts with M8.4 + M9-ci-fix, then land-ready

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high (resume of your M13 thread)
**Work dir:** worktree `tonewatch-m13`

## Situation
The PM reviewed M13-fix and it **passed**. All seven findings are verified in code, and the new golden scenarios cover cooldown repeats, disabled sets and known-then-unknown pages.

The PM has stash-rebased the worktree onto current `main` (`3cbeab9`). Since your last base, main gained:
- **M8.4, `7ca38fa`: legacy tones.cfg importer.**
  - `importers/tones_cfg.py`
  - `api/routes/import_tones_cfg.py`
  - the `_TonesCfgBodyLimitMiddleware` pure-ASGI body limit and `MAX_TONES_CFG_IMPORT_BYTES` in `api/app.py`
  - `save_config(..., audit=False)` in `api/deps.py`
  - the import CLI in `__main__.py`
  - the import preview/apply UI in `web/src/features/tonesets/ToneSets.tsx`
  - the `/api/import/tones-cfg` OpenAPI entries
  - threat-model entry `TM-029`
  - ASVS rows
- **M9-ci-fix, `9d5e0ef`.**
  - `configure_logging(..., data_dir=...)` in `api/app.py` and `logging.py`
  - uvicorn `log_config=None` in `service.py`
  - `scripts/check_runtime_export.py`
  - the `justfile`, where `TONEWATCH_E2E_PORT` now honours the environment

These files have **conflict markers**:
- `backend/src/tonewatch/__main__.py`
- `backend/src/tonewatch/api/app.py`
- `web/src/features/tonesets/ToneSets.tsx`
- `docs/security/asvs/checklist.csv`
- `docs/security/threat-model/README.md`
- `web/src/api/openapi.json`
- `web/src/api/generated/schema.d.ts`

## Required
1. **Resolve every conflict and keep both sides' behaviour.**
   - `api/app.py` keeps all of these:
     - the importer router and `_TonesCfgBodyLimitMiddleware` registration
     - `configure_logging(..., data_dir=settings.data_dir)`
     - your discovered-tones router and discovery wiring
     - the S5 security headers and 422 login handling
   - `__main__.py` keeps all of these:
     - M9 `service`/`selftest`
     - M10a `db checkpoint`
     - the M8.4 import CLI
     - your M13 CLI additions
   - `ToneSets.tsx` keeps both the import preview/apply UI and your "Create tone set from discovered draft" pre-fill flow. Existing web tests from both sides must pass.
   - Regenerate the two generated API files with `just gen-api`. Don't hand-merge them.
   - For `checklist.csv`, keep rows from both sides and re-derive every positive row's `path:line` from its unique snippet (QUOTE_ALL, LF). For the threat model, keep `TM-029` and your M13 clip/endpoint coverage, with unique IDs.
2. **Re-run the whole suite against the merged code.** In particular:
   - the importer API tests: body limit, chunked truncation, Content-Length
   - the Windows service/logging unit tests
   - your M13 golden, lifespan and API tests
3. **Update PROGRESS.** In `docs/PROGRESS.md`, keep main's lines (M8.4 `[x]`, M12.5) and yours. Leave the M13 lines as `[~] PENDING-REVIEW`, and use LF endings.

## Standing rules
- Never edit `docs/pm/**`.
- Never weaken a gate.
- Never print or commit anything from `backend/tests/fixtures/private/`.
- Never fetch, commit or push.

## Definition of done
- No conflict markers remain: `rg -n "^(<<<<<<< |=======$|>>>>>>> )" backend web docs scripts .github docker justfile` finds nothing.
- `just check` and `just test-slow` pass. Paste the tails.
- `api-drift` and e2e are host-only; the PM runs `ci-local` with `TONEWATCH_E2E_PORT=8794`.
- The final message lists each conflicted file and how you combined both sides.
