# Brief: LEAK1 — find and fix the test that leaks an aiosqlite connection

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-leak1` (branch `leak1`). **E2E port:** `TONEWATCH_E2E_PORT=8856`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Problem
On the Windows host, a full backend run (`just test`) failed once in an unrelated test:

```
FAILED backend\tests\unit\test_s4_security.py::test_rendered_log_output_redacts_secrets
E  ResourceWarning: <aiosqlite.core.Connection object ...> was deleted before being closed.
   (raised from aiosqlite Connection.__del__ while a WindowsPath under a TemporaryDirectory ... /config.yaml was being torn down)
pytest.PytestUnraisableExceptionWarning ... (pytest runs with -W error)
```

An **earlier** test left an aiosqlite connection open (an `AsyncEngine` not disposed, or a raw `aiosqlite.connect` not closed). Garbage collection later finalized it during whichever test happened to be running. Linux CI hasn't hit it yet, because GC timing differs. The failure is timing-dependent, but the leak is real. **Don't** touch `test_s4_security.py`, and **don't** add warning filters: fix the leak.

## Required
1. **Find the leaker(s) deterministically.** For example:
   - run the backend suite with `PYTHONTRACEMALLOC=20` and `-W error::ResourceWarning`, plus `-p no:randomly` if present
   - add a **temporary**, local-only autouse check (in a scratch `conftest` outside the repo, or via `-p` plugin/`--import-mode` tricks) that runs `gc.collect()` after each test and fails the test that leaked
   - or bisect by directory

   Suspects include recently added tests that create apps or engines: `test_m19i_backup.py`, `test_m19j_drill*.py`, `test_m19f_config_history.py`, `test_m19g_support.py`, `test_m19h_audit.py`, `test_m19d_credentials.py`, `test_m19e_*` (engines created without `await engine.dispose()` or `app.state.engine.dispose()`, or `create_app` used **without** its lifespan so the engine is never disposed), and production code paths (e.g. an app `create_database` whose engine isn't disposed when the lifespan isn't run). Paste the evidence identifying each leaker.
2. **Fix each leak at its source.** Dispose engines or close connections in the test (`try/finally` or fixtures). If production code creates an engine that is never disposed when the app is built without running its lifespan, make disposal reliable, e.g. dispose on lifespan shutdown **and** document that `create_app` without a lifespan must be closed by the caller. Don't change production behavior beyond that.
3. **Add a permanent regression guard** that makes any future leak fail **at the leaking test**, not at a random later one. For example, an autouse fixture in `backend/tests/conftest.py` (the root conftest only; **no subdirectory conftest**) that runs `gc.collect()` after each test with warnings-as-errors, so a `ResourceWarning` from an unclosed aiosqlite connection is attributed to that test. Keep its overhead reasonable: measure the full suite time before and after and report both. If the overhead of per-test `gc.collect()` exceeds ~15 %, propose a cheaper option (e.g. per-module) and implement that instead.

## Evidence (the report is rejected without it)
- The identified leaking test(s), with the command and output proving it: the guard failing them **before** the fix and passing after.
- A full `just test` run **twice** in a row, both green, with the pytest summary lines and suite times (before and after the guard).
- `just check` fully green with the coverage lines, and `git diff --stat`.
- **Honesty rule:** never call a failure "flaky" or "existing" without evidence.

## Standing rules
- Never edit `docs/pm/**`, `PLAN.md` or `backend/tests/unit/test_s4_security.py`. No new dependencies. Never weaken a gate or add warning filters.
- **Parallel engineer M19l** is in `api/routes/replay.py` and its tests. Don't touch those; if a leaker is there, report it instead.
