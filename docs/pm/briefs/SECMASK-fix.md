# Brief: SECMASK-fix — unblock (that test isn't S4), keep log redaction conservative, fix the regression

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0ad74-23d6-7b51-8d12-ad605d1d5eb5`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-secmask` (your uncommitted work stays). **E2E port:** `TONEWATCH_E2E_PORT=8830`. `docs/pm/briefs/SECMASK-secret-key-match.md` still applies.

## PM review of SECMASK
**Kept:**
- `is_secret_key` segment rule (last segment in the word list, or an explicit compound key)
- `restore_secrets` in `save_config`
- the new `test_secret_masking.py` tests

**Unblock:** the failing test at `backend/tests/unit/test_meshtastic.py:139` (`test_secret_key_helper_matches_masking_word_list`, asserting `prefix_<word>_suffix` is secret) is **not** the S4 suite.
- S4 means `backend/tests/unit/test_s4_security.py`, and your diff of it is empty.
- That test was added in M18b-fix to encode the old substring rule, which the PM has now deliberately replaced.
- **Update it** to the new rule: suffix keys are secret, and `token_ttl_s`/`prefix_password_suffix` aren't. Stopping was the right call given the brief's wording, and this settles it.

## Required changes
1. **Log redaction must stay conservative.** In `logging.py` you replaced the substring match with `is_secret_key`. That **weakens** log redaction:
   - `cookies`, `token_hash`, `session_token_prefix`, `csrf_header` and `set-cookie`-style variants that previously redacted would now be logged.
   - Over-redacting a log field costs nothing; under-redacting leaks credentials. So logs keep **substring** matching (the previous `_SENSITIVE` behaviour, including `set-cookie`), and **only** the API config masking and restore path use the precise `is_secret_key`.
   - Name the two predicates clearly, e.g. `is_secret_key` (config fields) and `is_sensitive_log_key` (logs).
   - Add a test proving `cookies`, `token_hash` and `x_csrf_token` are redacted in a structlog capture.
2. **Plural and header forms for config masking:** `is_secret_key` must also treat `cookies`, `passwords`, `secrets` and `tokens` as secret. Treat a plural last segment as the singular, or list them explicitly, and test it.
3. **Fix the regression you reported** ("an unrelated typed-dict test failure caused by the new save-path handling"). Paste the failing test name and line, explain the cause, fix it in the code (not the test, unless the test asserted wrong behaviour; justify it if so), and paste it passing.
4. **`restore_secrets` list matching:** falling back to index position when an item has no `id` can restore a secret into the wrong list item if a client reorders items.
   - Restore by index **only** when both the stored and submitted lists have no ids.
   - If a submitted `[REDACTED]` can't be matched to a stored item, return **422** rather than persisting the placeholder or a wrong secret.
   - Add a test with reordered id-less items that proves no cross-restore.

## Evidence (the report is rejected without it)
- The test table with failing and passing lines for the new and changed tests.
- **`just check` fully green** (paste the counts), `just e2e` on port 8830 (per-test lines), and `just ci-local` up to `api-drift`.
- The step 2 audit table from the original brief (each secret-bearing field, masked before and after). It's missing from your report.
- **Honesty rule:** as always.
