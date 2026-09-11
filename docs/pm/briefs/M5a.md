# Brief: M5a API core, auth and REST (M5.1–M5.3)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium

## Goal
Expose the running system over an authenticated FastAPI app: the app factory and lifecycle, auth including Home Assistant ingress trust, and the REST resources. This is the first network-facing code, so treat every input as hostile. A STRIDE threat model (S3) and an ASVS L2 audit (S4) follow and will test these exact paths. Work test-first.

Before starting, read `AGENTS.md`, `PLAN.md` (M5, Security assurance section), `docs/PROGRESS.md`, `backend/src/tonewatch/settings.py`, `config/models.py`, `config/store.py`, `pipeline/supervisor.py`, `storage/repository.py`, `recording/*`, and `__main__.py` (the `analyze` JSON schema in `docs/benchmarks.md`).

## In scope
M5.1, M5.2, M5.3. **No WebSocket, zeroconf or generated client**; that is M5b.

## Required design

### M5.1 App (`api/app.py`)
- `create_app(settings, *, supervisor=None, session_factory=None, store=None, clock=None) -> FastAPI`. Dependencies are injectable so tests use a temp data dir and a fake supervisor.
- The lifespan runs the Alembic upgrade, loads config, starts the supervisor, and stops it on shutdown.
- A `tonewatch serve` CLI starts uvicorn with host and port from settings. The default bind is `127.0.0.1`. The Docker and add-on images (M8, M10) set `0.0.0.0` explicitly.
- structlog JSON logging with a request id per request. **Never log** the token, the password, or `Authorization` or `Cookie` headers; a test must assert this.
- `GET /healthz` is unauthenticated liveness. `GET /readyz` is unauthenticated and returns 503 until the DB is migrated and the supervisor has started. Neither leaks versions or config.
- Security response headers on every response:
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
  - `X-Frame-Options: SAMEORIGIN` (HA ingress iframes the UI from the same origin)
  - a restrictive `Content-Security-Policy` for API responses
- **No CORS** by default.
- The error handler returns `{"detail": ...}` with **no stack traces or internal paths**.

### M5.2 Auth (`api/auth.py`)
- **API token:** 32 random bytes from the `secrets` module, URL-safe. It is generated on first run into `<data_dir>/api_token` with owner-only permissions: `0600` on POSIX, and on Windows the file stays in the user-owned data dir, with the limitation documented. Accept it as `Authorization: Bearer <token>`, compared with `hmac.compare_digest`. Add `tonewatch token show|rotate` CLI commands.
- **Optional UI password:**
  - Hash with stdlib `hashlib.scrypt` (n=2**15, r=8, p=1, 16-byte salt) and store it in the data dir. No new crypto dependency.
  - `POST /api/auth/login` sets a session cookie: `HttpOnly`, `SameSite=Strict`, `Secure` when the request came over HTTPS. The session id is random and server-side, with a 12 h idle expiry, and `POST /api/auth/logout` clears it.
  - **Login throttling:** after 5 failed attempts per client IP in 15 minutes, respond 429 with `Retry-After`.
  - Cookie-authenticated state-changing requests require a CSRF token: a double-submit header `X-CSRF-Token` matching a non-HttpOnly cookie. Bearer-token requests are exempt.
- **HA ingress trust:**
  - A request is trusted as ingress **only if** `settings.addon_mode` is true, the direct peer address (`request.client.host`, **not** `X-Forwarded-For`) equals `172.30.32.2`, **and** `X-Ingress-Path` is present.
  - Trusted ingress skips the password but is still authorised, because HA did the auth.
  - Outside add-on mode, `X-Ingress-Path` is ignored entirely.
  - Tests: a spoofed header from another IP is rejected; a correct IP without add-on mode is rejected; a spoofed `X-Forwarded-For: 172.30.32.2` is rejected.
- **Base path:** any URL the app returns (recording links, `Location` headers) is built relative to `X-Ingress-Path` when trusted ingress, otherwise to `/`. Test both.
- Every `/api/*` route except `auth/login` and `healthz`/`readyz` requires auth. Add a test that walks **all** registered routes and asserts that unauthenticated requests get 401. This catches routes added later without auth.

### M5.3 REST (`api/routes/`)
- **Tone sets, sources, alert targets:**
  - Full CRUD. Request and response schemas are the M1 pydantic models, which forbid extra fields.
  - Writes go through `ConfigStore` (atomic YAML), then `supervisor.reload(new_config)`. Changes apply live, with no restart.
  - `AppConfig` cross-reference validation errors return **422** naming the offending id.
  - Deleting a tone set that alert routing or sources still reference returns **409** listing the referrers.
  - Script alert targets can be **created, but not enabled via the API** unless `settings.allow_script_targets` is true (default false); otherwise 403. This is a deliberate guard against remote code execution.
- **Calls:**
  - `GET /api/calls` with filters (`source_id`, `toneset_id`, `since`, `until`) and cursor pagination (limit ≤ 200, default 50).
  - `GET /api/calls/{id}` returns the tone sets, recordings with URLs, and alert attempts.
- **Recordings:**
  - `GET /api/recordings/{recording_id}` streams the file by **DB id only**. Never take a path from the client.
  - The resolved path must sit inside `recordings_root`, re-checked at serve time.
  - Support `Range` for `bytes=` single ranges (206 and `Content-Range`), 416 on a bad range, correct `Content-Type` (`audio/mpeg`, `audio/ogg`), and `Accept-Ranges: bytes`.
- **`POST /api/tonesets/{id}/test`:** publishes a synthetic `ToneDetected` plus `CallClosed` through the bus, marked `test=true` in the event payload, so alert targets can be tested. Add the field to the events. It must **not** create a fake recording file.
- **`GET /api/devices`:** the same data as `tonewatch devices`.
- **`POST /api/analyze`:**
  - Multipart WAV upload, **max 20 MB** (413 beyond; enforce while streaming, not after reading everything), and max 10 minutes of audio.
  - Validate that the content is actually RIFF/WAVE; reject anything else with 415.
  - It runs the M2.7 analyze logic (refactor it into a shared function rather than shelling out) against the current tone sets, or ones supplied in the request, and returns the documented JSON schema.
  - Temp files are deleted afterwards.

## Tests
- `httpx.AsyncClient` with `ASGITransport` against `create_app` with a temp data dir and a real migrated SQLite DB.
- Cover:
  - every route's happy path
  - 401 for unauthenticated access, via the route walk
  - wrong token
  - ingress spoofing (3 cases)
  - login throttle and 429
  - CSRF missing or mismatched
  - Range (full, partial, suffix, 416)
  - recording path escape: the DB row points outside the root, so the response is 404 or 403
  - analyze: oversize 413, non-WAV 415, valid WAV returns detections
  - config CRUD 422 and 409
  - live reload called
  - script target 403
  - secrets absent from logs
- Coverage: add `api` to `check_package_coverage.py` at ≥90%.

## Constraints
- New dependencies: `fastapi`, `uvicorn[standard]`, `structlog`, `python-multipart`, and `httpx` (dev). Add them through `uv add`. They must pass `just security`, which runs the license and pip-audit checks.
- Don't modify PM-owned files: `scripts/license_check.py`, `.github/workflows/*`, `docs/pm/*`.

## Definition of done
- `just check` exits 0; run it **last** and paste the unfiltered tail, including the `check_package_coverage.py` lines.
- pre-commit over all files exits 0.
- `just security` exits 0.
- `docs/PROGRESS.md` ticks M5.1–M5.3.
- The final message includes a route table (method, path, auth requirement, status codes), a list of the security tests with pass status, and the `api` coverage.
