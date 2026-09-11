# PM review: M5a fails. The security claims aren't backed by tests.

Your report says "Security verification passed" and lists ingress-spoofing protection, login throttling, Range validation, path-traversal protection, secret-free logging and more. The test suite has **4 test functions** in `backend/tests/integration/test_api.py` (123 tests total, up from 119). Most of the listed behaviours have **no test at all**. For network-facing auth code, an untested security claim counts as a failure. The S3 threat model and S4 ASVS audit will rely on these tests as evidence.

The implementation exists (20 routes in `api/app.py`), so this round is mostly tests. Wherever a test shows a behaviour is actually missing or wrong, **fix the code**.

## 1. Required tests, each its own named test function
Put them in `backend/tests/integration/test_api_security.py` and `test_api_resources.py`. Use `pytest.mark.parametrize` where natural. The PM will grep for these names.

**Auth and ingress**
1. `test_every_api_route_requires_auth`: walk `app.routes`. For every `/api/*` route except `/api/auth/login`, call it without credentials and assert 401. It must discover routes dynamically, not from a hard-coded list.
2. `test_wrong_bearer_token_rejected` and `test_token_compared_in_constant_time`. For the second, assert `hmac.compare_digest` is used via monkeypatch or spy.
3. `test_token_rotate_invalidates_old_token`.
4. `test_ingress_trusted_only_in_addon_mode_from_supervisor_ip`, parametrized over four cases:
   - (a) add-on mode + peer 172.30.32.2 + `X-Ingress-Path` → allowed without password
   - (b) spoofed `X-Ingress-Path` from another peer IP → 401
   - (c) peer 172.30.32.2 but **not** add-on mode → 401
   - (d) `X-Forwarded-For: 172.30.32.2` from another peer → 401

   Set the peer address through the ASGI scope `client`, e.g. `httpx.ASGITransport(client=(ip, port))`.
5. `test_ingress_base_path_applied_to_generated_urls`: recording URLs and any `Location` header get the ingress prefix when trusted, and `/` otherwise.
6. `test_login_throttle_returns_429_with_retry_after`: 5 failures, then 429 with a `Retry-After` header. A different IP is not throttled.
7. `test_session_cookie_flags`: `HttpOnly` and `SameSite=Strict`; `Secure` only on https. Also the 12 h idle expiry, tested with an injected clock.
8. `test_csrf_required_for_cookie_state_changes`: missing token → 403, mismatched token → 403, bearer token → exempt.
9. `test_logout_invalidates_session`.

**Hardening**

10. `test_security_headers_present`: `nosniff`, `no-referrer`, `SAMEORIGIN`, CSP, on both an API response and an error response.
11. `test_errors_do_not_leak_internals`: force an exception in a route; the response body has no traceback, no file path and no exception text.
12. `test_secrets_never_logged`: capture structlog output while logging in and making bearer requests; assert the token, the password and the `Authorization`/`Cookie` values are absent.
13. `test_no_cors_headers_by_default`.
14. `test_readyz_503_until_ready_and_healthz_leaks_nothing`.

**Resources**

15. `test_toneset_crud_persists_yaml_and_reloads_supervisor`: assert the YAML on disk changed and that the fake supervisor's `reload` was called with the new config.
16. `test_config_crossref_error_is_422_naming_id` and `test_delete_referenced_toneset_is_409_listing_referrers`.
17. `test_script_target_enable_forbidden_unless_allowed`: 403 by default, allowed when `allow_script_targets=True`.
18. `test_calls_filters_and_cursor_pagination`: limit capped at 200; the cursor walks all rows without duplicates.
19. `test_recording_range_requests`, parametrized: full 200, `bytes=0-99` → 206 with the correct `Content-Range`, suffix `bytes=-100` → 206, out of range → 416. Check `Accept-Ranges` and the content types for mp3 and ogg.
20. `test_recording_path_outside_root_is_refused`: the DB row points outside `recordings_root` (and at a symlink escaping it, where the OS allows), giving 404/403 and no bytes served.
21. `test_analyze_rejects_oversize_413_while_streaming`: prove the body isn't fully buffered, e.g. by asserting a request larger than 20 MB is rejected before the handler reads it all, or by measuring peak read size. Also `test_analyze_rejects_non_wav_415`, `test_analyze_rejects_over_10_minutes`, `test_analyze_returns_documented_schema` (a real generated WAV page gives a detection), and `test_analyze_temp_files_removed`.
22. `test_toneset_test_endpoint_publishes_marked_events_without_recording_file`.
23. `test_devices_endpoint` (mock `sounddevice`).

## 2. Structure
`PLAN.md` puts routes in `api/routes/`. Twenty routes in `app.py` will not scale to M5b/M6. Split them into `api/routes/{auth,config,calls,recordings,analyze,system}.py` using `APIRouter`, with no behaviour change.

## 3. Coverage
`api/` must reach **≥90% per module** (today `analyze.py` is at 82%). Add `api` to `backend/scripts/check_package_coverage.py` per module, if it isn't already enforced per module.

## Reporting rule
Every security claim in your final message must name the test function that proves it. Omit any claim without a test.

## Definition of done
- `just check` exits 0; run it last and paste the unfiltered tail.
- pre-commit over all files exits 0.
- `just security` exits 0.
- The final message includes a two-column table: claim → proving test name.
