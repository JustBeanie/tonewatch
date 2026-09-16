# Brief: PIPECOV — pipeline coverage is timing-dependent and now below the 95 % gate

**From:** PM (Claude) · **To:** Codex engineer (new thread) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `C:\Users\beanie\Documents\Proj\tonewatch-pipecov` (branch `pipecov`). **E2E port:** `TONEWATCH_E2E_PORT=8824`.
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`. If pytest hits `PermissionError ... pytest-of-Beanie`, pass `--basetemp` pointing **outside** the repo.
**Git:** never write git state.

## Problem (PM evidence from host ci-local landing logs, `check_package_coverage.py` "pipeline" line)

| Landing | pipeline | Touched pipeline? |
|---|---|---|
| M19a | 96.70 % | yes |
| UI1 | 96.33 % | no |
| M19b (admin alerts: supervisor timer) | 95.88 % | yes |
| REL1 | 95.29 % | **no** |
| TZ1 | **94.94 % → gate FAIL** | **no** |

- Coverage of `tonewatch/pipeline/**` varies run to run on unchanged code, so some lines are only reached by timing-dependent paths (sleeps, races, background tasks, timeouts).
- It's now at the gate, so every landing can fail randomly.

### PM root-cause evidence (TZ1 landing)
- TZ1's host ci-local gave `pipeline: 94.94%` **twice in a row** (identical). `origin/main` gave 95.9 %.
- A per-line diff of `coverage.json` (main vs TZ1): the **only** pipeline difference is `pipeline/persistence.py:89-93`. That's the `except asyncio.CancelledError:` branch of `PersistenceConsumer.stop()` (`_abandon_commit`, cancel, gather, re-raise). It's covered on main and uncovered with TZ1's extra unit tests.
- No test targets that branch; it was only hit incidentally by some other test's shutdown ordering. Start there. A deterministic test must cancel the caller of `stop(timeout_s=...)` while it awaits the shielded task, and assert that `_abandon_commit` ran, the task was cancelled and `CancelledError` propagated.
- Then do the same for the other incidentally covered lines.

## Required
1. **Find the nondeterministic lines.**
   - Run the backend suite with coverage **3 times** on unchanged code, collecting per-file missing lines for `backend/src/tonewatch/pipeline/*` each time (coverage JSON, `missing_lines`).
   - Paste a table of lines that are covered in some runs but not others, with file:line and what code each is (e.g. the supervisor admin-alert timer loop, restart backoff, watchdog timeout).
2. **Write deterministic tests** that cover those lines on every run, with an injected clock, fake sleep or explicit events. No real `asyncio.sleep` waits over 50 ms and no reliance on scheduling order.
   - Test behaviour, not lines: each test asserts an observable outcome (a restart count, emitted events, a timer firing exactly N times, a clean cancellation on stop).
   - If a line is unreachable or dead, say so with evidence. Only remove it if it truly is dead, and show why.
3. **Also cover lines that are never covered** in `pipeline/supervisor.py` and `pipeline/channel.py`, where cheap and meaningful, so the package lands at **≥ 96.5 % on every run**.
4. **Never lower the gate**, add `pragma: no cover`, or exclude files.

## Also required: a repo-wide zeroconf guard (test hygiene, related nondeterminism)
- M18b-fix2 added `backend/tests/conftest.py` `forbid_unmarked_zeroconf` (the PM moved it there from `integration/conftest.py` because mypy rejected the duplicate `conftest` module name), but scoped it to `request.node.path.name == "test_meshtastic_api.py"` only.
- Other integration tests still start the real `ZeroconfAdvertiser` through the lifespan with default `Settings(...)`, e.g. `test_api.py:22,100,154,170` and `test_api_resources.py:129,209,372,427`. Those open a host mDNS socket on port 5353 and can leak it into later tests.
- Remove the filename scope so the guard applies to **every** integration test. Fix each failing test by passing `zeroconf_enabled=False` (via a shared helper where sensible), and keep `@pytest.mark.real_zeroconf` only where zeroconf behaviour is the subject (`test_discovery.py`, which already uses a fake).
- Evidence: the list of tests that tripped the guard before your fixes, and a full `just test` with the guard global.

## Evidence (the report is rejected without it)
- The nondeterminism table from step 1, from 3 baseline runs.
- **3 consecutive full `just test` runs after your change**, pasting the `pipeline:` line from each (all ≥ 96.5 %) and the pytest counts.
- A table mapping each new test name to the lines or behaviour it pins.
- `just check`, then `just ci-local` up to `api-drift`.
- **Honesty rule:** never call something flaky or existing without evidence from runs on unchanged `origin/main` code. Don't describe work you haven't done.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. No new dependencies. Test-only changes unless a real bug is found; if one is, show a failing test first.
