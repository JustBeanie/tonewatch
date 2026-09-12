# Brief: M9-ci-fix3 — `service uninstall` uses a nonexistent access-right constant

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high
**Work dir:** worktree `tonewatch-m9ci3` (branch `m9ci3`, based on `origin/main` `806f69a`). **E2E port:** `TONEWATCH_E2E_PORT=8800`.

## Situation
M9-ci-fix2 landed as `b743562`. On GitHub:
- **Docker is fully green.** The image is 304 MB, well under the 350 MB budget.
- **Windows `service-lifecycle` got further:** install, start, ready, stop and status (`stopped`) all pass, as does the DB open check.
- **It now fails at the last step, uninstall:**
  ```
  service ToneWatch: stop succeeded
  service uninstall failed: module 'win32service' has no attribute 'DELETE'
  ```

This bug has been in the code since M9 and was never reached before. In `backend/src/tonewatch/service.py`, `_WindowsServiceManager.uninstall` calls `self._open(win32service.DELETE)`. The standard `DELETE` access right (`0x00010000`) is not exported by `win32service`. It lives in `win32con.DELETE` (or `ntsecuritycon.DELETE`).

The unit tests missed it because the fake manager in `test_windows.py` replaces `_WindowsServiceManager` entirely for uninstall, and no test drives the real `uninstall` method through a fake `win32service` module.

## Required
1. **Fix the access right.** Import `win32con` alongside the other pywin32 modules, using the same lazy/Windows-only import pattern the file already uses for `win32service`. Open the service with `win32con.DELETE`. Keep the existing "service does not exist" handling: clear message, non-zero exit.
2. **Audit every other constant.** Check every `win32service.*` and `win32serviceutil.*` attribute used in `service.py` against what pywin32 actually exports, so no other latent `AttributeError` is waiting in `install`, `start`, `stop` or `status`.
   - Where you can run Python on this Windows host with pywin32 installed (`uv run --project backend python -c "import win32service, win32con; ..."`), prove each constant resolves.
   - Report the list.
3. **Add regression tests that exercise the real manager methods.** Extend the existing `FakeScm` pattern (monkeypatch `service.win32service`, and now also `service.win32con`) so that:
   - `_WindowsServiceManager().uninstall()` opens with the DELETE access right and calls `DeleteService`
   - uninstall of a missing service still maps to the clear error
   - install also runs through the real method with a fake, if it isn't covered already
   - on Windows with pywin32 installed, one test asserts `hasattr(win32con, "DELETE")` and `hasattr(win32service, <each constant service.py uses>)`, skipped on non-Windows with an explicit reason.

## Standing rules
- Never edit `docs/pm/**`.
- Never weaken a gate. Keep the workflow's assertions as they are.
- Never fetch, commit or push.

## Definition of done
- `just check` passes. Paste the tail.
- `just ci-local` with port 8800 reaches e2e. If the Windows Playwright launcher hangs only in teardown after every spec passes, say so exactly.
- The report maps the fix and tests, and lists every pywin32 constant `service.py` uses with proof that it resolves.
