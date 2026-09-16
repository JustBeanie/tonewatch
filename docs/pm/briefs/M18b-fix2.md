# Brief: M18b-fix2 — the new Meshtastic API tests start real zeroconf (a leaked mDNS socket fails ci-local)

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0ac33-4085-7eb3-8245-fef98757fd3a`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m18b` (the PM has already fast-forwarded it onto `origin/main` and staged the landing; don't touch `docs/pm/**` or `docs/PROGRESS.md`). **E2E port:** `TONEWATCH_E2E_PORT=8820`. Git rules are the same as before (never write git state).

## What failed (PM host ci-local, M18b landing)
- `1 failed, 574 passed`. `FAILED backend/tests/integration/test_tones_cfg_api.py::test_tones_cfg_api_auth_csrf_preview_apply_and_replace` with `PytestUnraisableExceptionWarning: ResourceWarning: unclosed <socket.socket ... laddr=('0.0.0.0', 5353)>` plus an unclosed `_ProactorDatagramTransport`.
- That test passes in isolation. The leaked socket is garbage-collected from an **earlier** test.

## Root cause (PM verified)
- `api/app.py:~230` starts `ZeroconfAdvertiser` when `settings.zeroconf_enabled and not settings.addon_mode`, and it's enabled by default.
- Every other integration test file that runs the lifespan passes `zeroconf_enabled=False` (`test_app_wiring.py`, `test_api_ws.py`, `test_m13_lifespan.py`, `test_m14a_live_stream.py`, `test_m15b_auto_squelch.py`, `test_spa.py`).
- `backend/tests/integration/test_meshtastic_api.py` never does. M18b raised its `lifespan_context` uses from 3 to 9.
- So each test opens a real mDNS socket on port 5353, **advertises on the host LAN**, and can leak it.

## Required
1. In `test_meshtastic_api.py`, create every `Settings(...)` with `zeroconf_enabled=False`. Prefer one module-level helper (`_settings(tmp_path)`) used by all tests.
2. **Guard against recurrence.** Add an autouse fixture in `backend/tests/integration/conftest.py` (create it if absent) that makes `ZeroconfAdvertiser` start fail loudly inside tests, **unless** a test opts in with a marker (e.g. `@pytest.mark.real_zeroconf`, registered in `pyproject.toml` because `--strict-markers` is on).
   - Mark the existing tests that intentionally exercise real zeroconf (check `test_discovery.py`) with that marker.
   - Show the guard failing when you temporarily remove `zeroconf_enabled=False` from one Meshtastic test, then restore it.
3. Change nothing else.

## Evidence (the report is rejected without it)
- `rg -n "Settings\(" backend/tests/integration/test_meshtastic_api.py` output.
- The guard's failing line from step 2, then its passing line.
- **Full** `just test` twice in a row, both green, with counts pasted. Run the full suite, not just the file: the failure was order-dependent.
- **Honesty rule:** never call a failure "existing" or "flaky" without running it on `origin/main` and pasting that result. Don't describe work you haven't done.
