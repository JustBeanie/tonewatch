# Brief: M19b-fix — admin alerts: the mandatory tests you skipped

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a7ee-bc32-7bc0-9ef3-e851208b2802`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19b`. **E2E port:** `TONEWATCH_E2E_PORT=8810` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.
**🚨 pytest temp dirs:** if you pass `--basetemp`, point it **outside the repo** (`$env:TEMP\tonewatch-pytest`).
**Git:** never write git state.

## Verdict on M19b: FAIL (tests)
**PM verified and kept:**
- `AdminAlertsConfig` with bounds and target validation (`models.py:545`, referenced ids checked at `:530`).
- `admin/alerts.py` (239 lines): clock-injected engine with hysteresis, latching, resolution and rate limits.
- A dedicated MQTT admin topic `tonewatch/<instance>/admin` (`mqtt.py:257`), separate from the call topic.
- Supervisor timer lifecycle; no fake `call_id` attempt rows.
- `just check` 556 passed/4 skipped; pipeline 95.65 %, alerts 90.19 %; e2e 4/4; s4 diff empty; no field-by-field `AppConfig` rebuilds.

**Why it fails:** the test file is 175 lines with **6** functions against **12** mandatory items. Missing outright:
- **A (partly):** no 422-through-the-API bounds test, and no pre-M19b YAML load test.
- **Config preservation:** no `admin_alerts` case in `test_all_config_mutation_paths_preserve_untouched_fields` (required by item 1 of the M19b brief).
- **H:** no dedupe test.
- **I:** no secret-absence assertion (no `password`/secret string anywhere in the test file).
- **J:** no proof that pages are unaffected (no `ToneDetected` in the test file).

## Required
Add these as **separately named** tests; the report maps name → letter.
1. **A. Config:**
   - Defaults match the brief.
   - `POST /api/config` (or the source/target path that validates config) returns **422 naming the field** for: `disk_used_pct=49`, `target_failures=1`, `realtime_factor_min=0.9`, `max_per_hour=0`.
   - An unknown target id is rejected, naming the id.
   - A **pre-M19b YAML** (no `admin_alerts:` key) loads unchanged and yields `enabled=False`.
2. **Config preservation:** add an `admin_alerts` case to `test_all_config_mutation_paths_preserve_untouched_fields` in `backend/tests/integration/test_api_resources.py`, with a non-default `AdminAlertsConfig` in the baseline so a dropped field fails the test.
3. **H. Dedupe:** two evaluations in the same tick, with the condition true both times, send **exactly one** notification; assert the sender call count.
4. **I. Secrets:** configure a webhook target whose URL embeds credentials and an MQTT target with a password, fire an admin alert, and assert that neither the payload dict, the serialized JSON, nor captured log output (`log.SetOutput`-style capture via `caplog`) contains the credential or password.
5. **J. Pages unaffected:** with admin alerts **enabled and firing**, handle a normal `ToneDetected` and assert the recorded call payload and the per-target attempt sequence are **identical** to the same scenario with `admin_alerts.enabled=False` (compare the captured payloads for equality, not just counts).
6. **Verify the conditions you did write actually cover C–F separately:** disk-used and disk-forecast have distinct condition keys, target-failures, squelch-stuck-open and realtime-factor each fire and clear. If one of your combined tests doesn't assert a condition's own key and its `resolved` follow-up, split it out.

## Evidence (the report is rejected without this)
- A table: test name → letter (A–L), including the ones that already pass.
- For each new test: the first-run line (failing, or "passes immediately" stated) and the passing line.
- The pytest count before (556) and after.
- `just check`, `just e2e` (port 8810), and **`just ci-local` run to completion** up to api-drift; paste `git diff --stat -- web/src/api`. Do not stop ci-local early: the PM lands from it.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` and pasting the result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. Never weaken a gate or coverage threshold.
- No new dependencies. No real radio data.
- Never write git state. Don't describe work you haven't done.
