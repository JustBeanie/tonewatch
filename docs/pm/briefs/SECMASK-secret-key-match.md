# Brief: SECMASK — secret masking over-matches non-secret keys (e.g. `token_ttl_s`)

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-secmask` (branch `secmask`). **E2E port:** `TONEWATCH_E2E_PORT=8830`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Bug (PM evidence)
- `api/audit.py` `is_secret_key(key)` returns true when **any** of `password|secret|token|authorization|cookie|csrf` is a **substring** of the key.
- So `GET /api/config` returns `live_stream.token_ttl_s: "[REDACTED]"`. A client that GETs the config and PUTs it back gets **422** (`token_ttl_s: Input should be a valid integer ... input: "[REDACTED]"`); the M16b agencies UI hit exactly this.
- The same over-match hides non-secret values in audit logs.

## Required
1. **Redefine secret keys precisely.** A key is secret when, after lowercasing and splitting on `_`/`-`, its **last** segment is one of `password`, `secret`, `token`, `authorization`, `cookie`, `csrf`, **or** the full key is in an explicit set (e.g. `api_key`, `private_key`, `passphrase`, `x-api-key`; add what the codebase needs).
   - Under this rule `token_ttl_s` is not secret; `password`, `ui_password`, `mqtt_password`, `secret`, `live_secret` and `api_token` are.
   - HTTP headers such as `Authorization`, `Cookie` and `X-CSRF-Token` must still be masked in request logs. Check `api/app.py` and any logging middleware that uses the same helper.
2. **Audit every model field and every place `mask_secrets`/`is_secret_key` is used**: config models, settings, request-log redaction, audit events, diagnostics and the support bundle if it exists.
   - Produce a table in the report with each secret-bearing field and whether it's masked before and after.
   - **No field that's currently a real secret may become unmasked.**
3. **Keep the PUT secret-preserve behaviour from M18b** working with the new rule. The round-trip tests for mqtt, webhook and meshtastic stay green.
4. **Full config round-trip:** `GET /api/config` then `PUT /api/config` with the same body (plus `If-Match`) succeeds unchanged, and stored secrets are preserved.

## Mandatory tests (write first; show each failing)
- **A.** Parametrized `is_secret_key` tests: `token_ttl_s` is False; `password`, `ui_password`, `mqtt_password`, `secret`, `api_token`, `Authorization`, `Cookie` and `X-CSRF-Token` are True; plus any keys found in step 2.
- **B.** A full config GET, then PUT, via ASGI with a config that has live_stream settings and alert targets with secrets: 200, the stored config is unchanged, and secrets are preserved.
- **C.** Request-log redaction still masks the `Authorization` header and cookies (a `caplog` or structlog capture).
- **D.** `git diff origin/main -- backend/tests/unit/test_s4_security.py` is empty. If an S4 test encodes the old substring behaviour, **stop and report it**; don't edit S4.

## Evidence (the report is rejected without it)
- The step 2 audit table, the tests with their failing and passing lines, `just check`, then `just ci-local` up to `api-drift`, and `git diff --stat`.
- **Honesty rule:** as always.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. No new dependencies. No subdirectory `conftest.py`. Never weaken a gate.
