# Brief: M19b-fix2 — make test J prove what it claims

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0a7ee-bc32-7bc0-9ef3-e851208b2802`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m19b`. **E2E port:** `TONEWATCH_E2E_PORT=8810` (leave `TONEWATCH_E2E_URL` unset).
If `uv` reports the Python minor-version link error, set `UV_PYTHON=C:\Users\beanie\AppData\Roaming\uv\python\cpython-3.13.13-windows-x86_64-none\python.exe`.
**🚨 pytest temp dirs:** a `backend/.pytest-tmp` is present in the worktree again; it breaks the PM's host gate. Never create temp dirs inside the repo. If you need `--basetemp`, use `$env:TEMP\tonewatch-pytest`.
**Git:** never write git state.

## Verdict on M19b-fix: nearly there
**PM verified and kept:** 15 tests (424 lines) mapping A–L; 422 through the API per field; pre-M19b YAML load; `admin_alerts_update` added to the config-preservation parametrization with a non-default baseline; dedupe; distinct disk-used and forecast keys; target failures, squelch stuck open and realtime factor each fire and resolve; **I** checks both embedded credentials against the serialized payload and `caplog`. `just check` 566 passed/4 skipped, e2e 4/4, s4 diff empty.

## One test is too weak: J
`test_m19b_j_pages_payloads_are_identical_with_admin_alerts_on_or_off` has two holes:
1. **It can pass vacuously.** It asserts `payloads[0] == payloads[1]` but never that either list is non-empty. If no page payload were delivered at all, both lists would be `[]` and the test would still pass.
2. **Admin alerts are never actually firing.** It only toggles `AdminAlertsConfig(enabled=...)`. The M19b brief requires admin alerts **enabled and firing** while a normal page is handled, so it proves an active admin notification path doesn't interfere with paging.

## Required
- In J (keep the name), for the `enabled=True` case, drive the admin engine so a condition is **firing** (for example evaluate with a failing target or disk condition using your clock-injected engine) and deliver that admin notification through the same dispatcher **before and after** handling the `ToneDetected`.
- Assert, for both runs:
  - the page payload list has **exactly** the expected number of entries (non-empty, e.g. `== 1` for the pre-alert phase),
  - the page payloads are equal across the off and on runs,
  - in the on run, the admin notification was also sent (separately captured), and **no** admin payload leaked into the page list (e.g. no `kind: "admin"` among page payloads).
- Show it would catch a regression: temporarily make the dispatcher skip page delivery while admin alerts fire, paste the failing line, then restore.

## Evidence
- The failing-then-passing lines for J, including the temporary regression proof.
- `just check`, `just e2e` (port 8810), and `just ci-local` to api-drift, plus `git diff --stat -- web/src/api`.
- **Honesty rule:** never label a failure "existing" or "flaky" without running the same test on `origin/main` and pasting the result.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. Never weaken a gate.
- No new dependencies. Never write git state. Don't describe work you haven't done.
