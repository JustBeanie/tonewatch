# Brief: UI1-fix — make the live-listen e2e test pass, and close the console-spy gap

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a7c8-9b48-7fb0-b55c-10785cbacd0f`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-ui1`. **E2E port:** `TONEWATCH_E2E_PORT=8809` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.
**🚨 pytest temp dirs:** if you need `--basetemp`, point it **outside the repo** (`$env:TEMP\tonewatch-pytest`); a `.pytest-tmp` inside the worktree breaks the PM's host gate.
**Git:** never write git state.

## Verdict on UI1: FAIL (one failing e2e test, one missing assertion)
**PM verified and kept:**
- `just check` passes on the host: backend 531 passed/4 skipped, web **52 passed**, statements 87.08 %, branches 80.31 %; no `web/src/api` drift; backend source untouched.
- Tests use role queries throughout (29 `getByRole`/`findByRole`, zero `querySelector`).
- Live player, mint/copy/expiry, stop cleanup, listener counts, squelch modes with validation, meter and lamp, calibrate-without-saving, diagnostics badges and the rebroadcast disclaimer are all present.

**PM host `just e2e` (port 8809) result:** `4 passed, 1 failed`. Only your new spec fails:

```text
live listen starts and releases a file-source listener
> 90 | await expect(source.locator("audio")).toHaveAttribute("src", /live\.mp3/);
Error: element(s) not found  (no <audio> ever appears after clicking Listen live)
```

So this is a real gap, not flakiness or an environment quirk.

## Required
1. **Enable live streaming in the e2e fixture config, not through the UI.** The generated config has no `live_stream` section, so the feature is off by default for the whole run.
   - Edit `scripts/e2e_fixture.py` `_config()` to emit a `live_stream:` section with `enabled: true` (keep the other defaults). The source already defaults to `live_stream_enabled: true`.
   - This is **test infrastructure only**: don't change any product default. Live streaming stays off by default in real installs.
   - Then simplify your spec: drop the Settings toggling and go straight to Sources.
2. **Make the spec pass end to end:** click Listen live, assert the `<audio>` `src` matches `live.mp3`, the listener count reads 1, then Stop and assert it returns to 0.
   - If the count needs a WS round trip, wait on the visible text rather than a fixed timeout.
   - If the mint fails for another reason, diagnose it: check the browser console and the API response in the trace, and fix the real cause. Paste the diagnosis in the report.
3. **Add the missing console assertion (brief item C).** In the Vitest suite, spy on `console.log`/`info`/`warn`/`error`, mint and copy a URL, and assert the signed URL (and its token) never reaches any console call.
4. **Keep the other 4 specs green** and the Vitest suite green.

## Evidence
- The full `just e2e` summary line (all 5 specs) from your own run, plus `just check`.
- The diff excerpt for `scripts/e2e_fixture.py` and the spec.
- The failing-then-passing lines for the console-spy test.
- `just ci-local` up to api-drift, plus `git diff --stat -- web/src/api`.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` and pasting the result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. Never weaken a gate or coverage threshold.
- No product default changes; no backend behaviour changes. No new runtime dependencies.
- Never write git state. Don't describe work you haven't done.
