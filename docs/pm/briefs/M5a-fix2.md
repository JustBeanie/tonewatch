# PM review, round 2: M5a still fails. Four named tests or claims are hollow.

**Escalated:** targeted sub-brief on gpt-5.6-luna **high** (second failed review at medium).

The 29 test names now exist and `just check`, pre-commit and `just security` all pass. Good progress. PM inspection of the implementation and the tests still found four problems. Fix exactly these; nothing else is in scope.

## 1. Logging is not configured, so `test_secrets_never_logged` proves nothing
`structlog.configure` is never called anywhere. `structlog.get_logger` falls back to its default `PrintLogger`, which writes to **stdout**. The test inspects `caplog` (stdlib logging), which never receives structlog output, so it passes whether or not secrets are logged. M5.1's "structlog JSON logs with request id" is also unimplemented.
- Add `tonewatch/logging.py` with `configure_logging(level, *, json=True)`:
  - structlog routed through stdlib logging
  - JSON renderer
  - ISO UTC timestamps
  - `contextvars`-based `request_id`, set by middleware per request and returned as the `X-Request-ID` response header
  - a **redaction processor** that masks keys and values for `authorization`, `cookie`, `set-cookie`, `password`, `token`, `csrf`, and any value equal to the loaded API token
- Call it from `create_app`, or the lifespan, and from the CLI.
- Rewrite the test to capture the **actual rendered log output**: `structlog.testing.capture_logs` for events, **and** `capsys`/`caplog` on the configured stdlib handler for rendered JSON.
  - Exercise login with the password, a bearer request, a cookie request and a failed login.
  - Assert that the secrets are absent **and** that at least one access log line **was** emitted, so the test fails if logging goes silent.
- Add `test_request_id_propagates_to_logs_and_header`.

## 2. Routes were not actually split
`api/app.py` still defines 18 routes; `routes/{analyze,calls,config,recordings,system}.py` define **0**. Move each group into its router module (`APIRouter` with shared dependencies) and include the routers in `create_app`. `app.py` keeps only the factory, middleware, exception handlers and lifespan. There must be no behaviour change: all 159 existing tests pass unchanged, and the route-walk auth test must still discover every route.

## 3. `test_ingress_base_path_applied_to_generated_urls` doesn't check URLs
It only asserts status codes. Seed a call with a recording in the DB, then:
- As trusted ingress with `X-Ingress-Path: /api/hassio_ingress/abc`, assert that `GET /api/calls/{id}` returns recording URLs starting with `/api/hassio_ingress/abc/api/recordings/`.
- As a bearer client, assert that the same URLs start with `/api/recordings/`.
- Spoofed `X-Ingress-Path` from an untrusted peer with a valid bearer token: assert the URL is **not** prefixed. A header must never inject a path.

## 4. The upload size limit is enforced after buffering, not while streaming
Starlette/python-multipart has already spooled the entire body before the handler's `file.read()` loop runs.
- Add an ASGI middleware or a route-level body guard for `/api/analyze`:
  - reject with **413 immediately** if `Content-Length` exceeds the limit
  - otherwise count bytes while `receive()` yields body chunks and abort at the limit, without reading the rest
  - keep a small allowance for multipart overhead, and document it
- Rewrite `test_analyze_rejects_oversize_413_while_streaming`:
  - (a) Oversized `Content-Length` → 413, asserting the handler never ran (spy).
  - (b) Chunked upload with no `Content-Length`, via a custom ASGI `receive` that yields 1 MB chunks and counts how many were pulled → 413, having pulled no more than about limit/1MB + 2 chunks.

## Definition of done
- `just check` exits 0 (run it last; paste the unfiltered tail), pre-commit over all files exits 0, and `just security` exits 0.
- `grep -c "@router\."` across `api/routes/*.py` ≥ 18, and `app.py` defines no route handlers.
- The final message maps each of the 4 findings to what changed and to the proving test names.
