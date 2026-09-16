# Brief: M18b-fix — truncation flag is wrong at the default max_bytes; tighten the secret-preserve rule; missing evidence

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0ac33-4085-7eb3-8245-fef98757fd3a`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-m18b`. **E2E port:** `TONEWATCH_E2E_PORT=8820`. Environment and git rules are the same as M18b.

## Verdict on M18b: PARTIAL
**PM verified and kept:**
- The preview endpoint uses the real `render_message`, has `write_auth`, and makes no broker connection. The test monkeypatches `aiomqtt.Client` to raise, and the password is absent from the response.
- The generic PUT secret-preserve for `[REDACTED]`/omitted values, with a round-trip test for mqtt, webhook and meshtastic.
- "Send test" now targets `alert-targets/{id}/test`.
- The race test now uses two distinct tone sets (`county-fire`, `city-ems`).
- 12 Vitest cases and the e2e spec. The report states `just check` 569 passed, and e2e 6/6.

**Why it isn't a pass:**
1. **Bug: `truncated` is wrong whenever `max_bytes == 200`, which is the default.**
   - `config.py` preview computes `untruncated = render_message(target.model_copy(update={"max_bytes": 200}), ...)`. `render_message` itself truncates to 200.
   - So for a template whose rendered text exceeds 200 bytes with the default `max_bytes` 200, `text == untruncated` and the endpoint reports `truncated: false` while the text was cut.
   - Fix it by rendering the untruncated text without any byte cap: factor the pre-truncation rendering out of `render_message` into a helper that both the sender and the preview use, so `render_message` = `truncate_utf8(render_untruncated(...), max_bytes)`. Then compare byte lengths.
   - Keep the sender's output byte-identical: the existing golden and hypothesis tests must pass unchanged.
2. **The secret-preserve rule duplicates the word list.**
   - PUT preserves only keys containing `password`/`secret`, but `mask_secrets` masks every key matching `api/audit.py` `_SECRET_WORDS` (`token`, `authorization`, …).
   - Any future target field named e.g. `api_token` would be masked on GET but then saved as the literal `"[REDACTED]"`.
   - Reuse `_SECRET_WORDS`, via a small public helper such as `is_secret_key(key)` in `api/audit.py` used by both.
   - Also reject (422) any `"[REDACTED]"` value that reaches validation for a key with **no** stored value, so the placeholder can never be persisted.
3. **Test E is incomplete.** The brief required the Meshtastic test-send to publish once **with the `TEST ` prefix**. No test asserts the prefix; the route test only checks the audit row.
4. **`Alerts.tsx` is 432 lines.** The brief said to split past ~200. Split it into `MeshtasticFields.tsx`, a `useMeshtasticPreview` hook, and the list/form. No behaviour change; Vitest stays green.
5. **Missing evidence table.** The brief required test name → letter, with each test's first-run failing line or "passed immediately" and its passing line. The report gave a one-line summary instead.
   - The "Windows `UTC` validation issue" is unexplained, and no model or source diff shows where it was fixed. Explain exactly what failed and what changed (file:line).

## Required tests (write first; show each failing before the fix)
- **A2. `test_meshtastic_preview_flags_truncation_at_default_max_bytes`:** `max_bytes` 200, a template rendering to more than 200 bytes (multi-byte characters included). Assert `truncated is True`, `bytes <= 200`, and a clean decode. It must fail on the current code; paste the failing line.
- **A3.** A template that renders to exactly `max_bytes` gives `truncated is False`.
- **D2.** PUT with `"[REDACTED]"` for a secret key when the stored value is `None`/empty gives 422, and the stored config is unchanged.
- **D3.** A unit test that `is_secret_key` matches every `_SECRET_WORDS` entry and that `mask_secrets` uses it.
- **E2.** The Meshtastic test-send through the route with a capturing fake publisher: exactly one publish, and the text starts with `TEST `.

## Gates and evidence
- The evidence table, as described in item 5.
- `just check` (with before and after counts), `just e2e` on port 8820, and `just ci-local` up to `api-drift`. Paste `git diff --stat`.
- **Honesty rule** as before. Don't describe work you haven't done.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. Never write git state. No new dependencies.
- Don't change sender output bytes. No URLs or tokens on the mesh.
