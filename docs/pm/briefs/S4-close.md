# S4-close: finish the checklist conservatively (unverified means gap)

**Resuming the terra thread.** Model gpt-5.6-terra high, in the `tonewatch-s4` worktree.

Thanks for the honest "Not complete" report. That's exactly what the PM needs. The TLS test rewrite is correct, and it **passes on the PM host**. Your fixes to the OAuth, JWT, redirect, V15.3.4 and V3.4.6 rows are correct too.

## Strategy change (PM decision)
Three agent rounds on a 253-row grid drifted into templated mappings every time. From now on, **a row is `pass`/`fixed` only when you've opened the evidence line and the test, and both directly enforce the requirement. Everything else is `gap`**, with a `GAP-###` and a target milestone, or `na` with a feature-specific reason. Expect roughly 15–30 `pass`/`fixed` rows. Later S-track milestones convert gaps chapter by chapter, and that's fine. **Honest gaps beat a full-looking checklist.**

## PM host `just check` on your tree: 277 passed, 2 failed
1. **`test_asvs_header_evidence_names_the_enforced_header` fails on V3.4.1 (HSTS).**
   - The row is `pass` but cites `api/app.py:136` (`X-Content-Type-Options`).
   - The app does not send HSTS. It's a plain-HTTP local service, and TLS is terminated by a reverse proxy or HA.
   - Make the row `accepted` with a new AR (TLS/HSTS is a deployment concern, expiry ≤90 days, with a pointer to M12 deployment docs) or `gap`.
2. **`test_asvs_feature_specific_requirements_are_not_keyword_matched` fails on V7.4.1** (`fixed` citing the log-redaction test), and it also flags V14.1.1, V15.3.1 and V16.5.1.
   - **Root cause:** the regex has no word boundaries. PM check: `turn` matches "re**turn**" and the like, giving **13 false positives** (V6.8.2, V6.8.4, V7.4.1, V9.1.x, V9.2.x, V10.1.1, V10.4.9, V10.5.1, V15.3.1, …).
   - **Fix:** `\b(oauth|authorization code|refresh token|turn|webrtc|dtls|jwt|self-contained token)\b`, then re-evaluate those rows on their merits.

## Validator bug that let templates through
`test_asvs_notes_are_not_templated` splits sentences with `re.split(r"(?<=[.!?])\\s+", …)`. In a raw string, `\\s` matches a literal backslash followed by `s`, so notes are **never split** and a shared sentence can't be detected.
- Fix it to `\s+`.
- Remove the suffix you appended to evade the repeat check, "Requirement-specific regression coverage is recorded for Vx.y.z". Notes must stand alone.

## Rows still wrong in the PM's second 15-row sample (make each honest)
| Row | Recorded | Problem |
|---|---|---|
| V6.5.5 (OOB/TOTP codes) | `fixed`, citing `test_upload_decode_timeout` | No OOB/TOTP exists, so it's **na** |
| V7.4.1 (session termination) | `fixed`, citing the log-redaction test | Cite the real logout/session-invalidation line and a test asserting that the old session is rejected, or mark it gap |
| V16.2.2 (synchronised time sources) | cites the audit recorder | gap, or accepted as a deployment/NTP concern |
| V4.4.2 (WebSocket Origin check) | cites `MAX_CONNECTIONS = 20` | Cite the real Origin check and its test, or gap |
| V4.4.4 | cites `MAX_CONNECTIONS = 20` | The evidence must be the auth line |
| V3.5.2, V3.4.2 (CORS) | evidence is a blank line in a **test** file | Evidence must be under `backend/src/` or `docs/`, never `backend/tests/`. Cite the absence of CORS middleware in `app.py` with a test asserting no `Access-Control-Allow-Origin`. |
| V5.3.2 (server-generated file paths) | cites the FFmpeg protocol whitelist | Cite the recordings path construction (`encoder.py`) or gap |
| V15.3.2 (don't follow redirects) | cites the whitelist constant | Cite `follow_redirects=False` / `max_redirects` |
| V17.1.1 | `na` with reason "no OAuth" | The reason must be no WebRTC/TURN |

## Validator additions
- Evidence paths for `pass`/`fixed`/`accepted` must start with `backend/src/` or `docs/`.
- The evidence line must be non-blank.
- `na` notes must not reuse another row's reason sentence unless the rows share a feature: allow the OAuth family, forbid cross-family reuse. **Keep this simple.**

## Out of scope
`just api-drift` differences come from the uncommitted S4 generated API files. That's expected in PM-review mode, and the PM verifies drift after staging. **Don't touch them.** If `just check` hangs inside your sandbox, say so. The PM runs it on the host.

## Definition of done
- `test_asvs_checklist.py` passes: run `uv run --project backend python backend/scripts/run_pytest.py backend/tests/unit/test_asvs_checklist.py --no-cov` and paste its tail.
- `pre-commit run --all-files` and `just security` pass.
- **Final message:**
  - the per-chapter status table
  - **every** remaining `pass`/`fixed` row (roughly 15–30), each with the evidence line's actual code and the specific assertion in the cited test
  - the AR list with expiries
