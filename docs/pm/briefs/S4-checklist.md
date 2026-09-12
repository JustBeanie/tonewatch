# Sub-brief: ASVS 5.0 L1/L2 checklist, row-by-row judgement (escalated)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-**terra**, high

**Why this is escalated:** luna·high failed this exact artifact twice. S4 cited 5 tests for 210 rows. S4-fix spread the citations to satisfy numeric caps, but the mappings are still keyword matches. **Scope is ONLY the checklist and its evidence.** No product code changes. Test changes are limited to `test_asvs_checklist.py` plus, where a real control truly lacks a direct test, a small new test that asserts that control.

You are in the `tonewatch-s4` worktree. Read `docs/security/asvs/source/*.csv` (the pinned official text), `docs/security/asvs/checklist.csv`, `docs/security/gaps.md`, `docs/security/accepted-risks.md`, `docs/security/threat-model/README.md`, `docs/decisions/*.md`, and the backend code each row cites.

## 0. First: a wrong TLS premise and a non-portable security test (small, but it blocks CI)
`backend/tests/unit/test_s4_security.py::test_stream_https_certificate_verification`, ADR-0005 and AR-004 all claim "the Windows PyAV wheel cannot establish HTTPS". **That is false.** The engineer's probe ran inside the Codex sandbox, whose Windows user has **no schannel credentials**; `git` and `curl` fail there with `SEC_E_NO_CREDENTIALS` for the same reason. On the PM host's `just check` this test **fails**: `DID NOT RAISE`, because `tls_verify=0` opened fine.

PM measurements, as a normal Windows user, PyAV 18.1.0 / libavformat 62.12:

| Case | Result |
|---|---|
| Local self-signed HTTPS, `tls_verify=0` | **decoded**; TLS works |
| Local self-signed HTTPS, `tls_verify=1` + certifi `ca_file` | **refused**; verification works |
| Local self-signed HTTPS, `tls_verify=1` + `ca_file=<test cert>` | **refused**. The Windows (schannel) backend **ignores `ca_file`** and uses the Windows certificate store. |
| Public `https://example.com/`, `tls_verify=0` / `tls_verify=1` / `tls_verify=1` + certifi | all passed the TLS handshake and failed only at media parsing (`InvalidDataError`), so S4's config does **not** break public-CA feeds on Windows |

**You can't run TLS inside your sandbox**, so design the test to be correct on every OS and let CI prove it:
- **Rewrite the test to branch on measured capability.**
  1. **Capability probe:** a `tls_verify=0` open of the local self-signed server. If that raises, it's the "no TLS in this environment" branch: `pytest.skip` with a reason naming the sandbox/schannel credential limitation. **Don't** assert it as product behaviour.
  2. **Verification always:** `_decode_url` (the product options: `tls_verify=1` + certifi) must be **refused** for the self-signed server, with target hits unchanged.
  3. **`ca_file` branch:** `tls_verify=1` with `ca_file=<test cert>` decodes on backends that honour `ca_file`, and is refused on Windows schannel. Assert the platform-appropriate outcome, and log which branch ran (a logging line).
  4. Missing `openssl` is a `pytest.skip` with a reason, not a failure.
- **Correct ADR-0005's TLS section and AR-004** with the PM measurements above. Delete or rewrite AR-004: the residual risk is only that `ca_file` is ignored on Windows, where the OS store is used.
- **No stream code change** is expected. If the Linux CI result later shows `ca_file` breaking public feeds, the PM will send that separately.

## What PM sampling found (15 random pass/fixed rows; about 10 wrong)
| Row | Recorded | Why it's wrong |
|---|---|---|
| V10.4.3: the OAuth authorization code is short-lived | `fixed`, citing `analyze_wav_with_timeout` / `test_upload_decode_timeout` | There is no OAuth. **N/A.** |
| V10.4.2: the OAuth authorization code is single-use | `pass`, citing token generation | **N/A** (no OAuth) |
| V9.2.2: self-contained token type validation | `pass`, citing `secrets.token_urlsafe` | Tokens are opaque. **N/A.** |
| V17.1.1: the TURN service address restriction | `fixed`, citing stream URL policy | There is no WebRTC or TURN. **N/A.** |
| V3.4.1: Strict-Transport-Security on all responses | `pass`, citing the `X-Content-Type-Options` line | Check whether HSTS is actually sent. If not, it's a `gap`, or `accepted` because TLS termination is a deployment concern: cite an ADR or AR. |
| V3.4.6: CSP `frame-ancestors` | `pass`, citing the `nosniff` line | Cite the actual CSP line **if** it contains `frame-ancestors`; otherwise `gap`. |
| V4.1.2 / V3.7.2: HTTP→HTTPS redirects, and redirects only to allowed hosts | cite the FFmpeg protocol whitelist | Those are browser-facing web-app redirects, not the stream decoder. |
| V15.3.4: the original client IP comes from trusted proxy data only | cites the bounded-throttle test | The relevant control is the ingress trust logic (`172.30.32.2` + `X-Ingress-Path`). Cite that and its spoofing test, or `gap`. |
| V3.2.1: prevent browsers rendering content in the wrong context | cites the upload size limit | Unrelated control |

Every note also ends with the same templated sentence: "The cited test exercises this exact control."

## Method (per row, all 253)
1. Read the requirement text. Decide **applicability** first, with a concrete reason naming the absent feature: no OAuth/OIDC, no self-contained tokens, no WebRTC, no user self-registration or password reset (a single UI password plus a bearer token), no payment, no file download from user-supplied URLs except streams.
2. If it applies, find the **specific** control. `evidence` must be the path:line where that control is implemented. A reader who opens that line should see the requirement being enforced: the header value, the check, the constant.
3. `test` must be a test whose **assertions** fail if that control is removed. Open the test and confirm it. If no such test exists but the control does, write a minimal new test asserting exactly that control. If the control doesn't exist, the row is a `gap`.
4. `pass` means the control existed before S4. `fixed` means S4 or S4-fix added it; check with `git diff 9ef8f0c --stat` and the file history.
5. `notes`: one row-specific sentence naming the mechanism. **No shared boilerplate.**
6. `gap` rows each get a `GAP-###` entry with a concrete target milestone.
   - Honest gaps are expected, and many are acceptable at this stage.
   - Re-examine the existing 190 gaps too: some may really be `na` (not applicable) or `pass`.
7. `accepted` rows need an `AR-###` entry with an expiry ≤90 days, and a rationale a security reviewer would accept.

## `test_asvs_checklist.py` additions
Keep every existing check, and add these:
- **Denylist of evidence/requirement mismatches:** rows mentioning OAuth/authorization code/refresh token, TURN/WebRTC/DTLS, or JWT/self-contained tokens must be `na` unless the row's `notes` explicitly justify applicability.
- **Header evidence:** for rows whose requirement names a specific HTTP header (`Strict-Transport-Security`, `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors`), a `pass`/`fixed` row's evidence line must contain that header name (case-insensitive).
- **Templated notes:** reject any note containing "The cited test exercises this exact control" or any other sentence shared by more than 2 rows.

## Deliverables
- `checklist.csv`, `gaps.md` and `accepted-risks.md`, all consistent. Re-run SAMM scorecard generation, since evidence counts may change.
- **Final message:**
  - a per-chapter table: applicable / pass / fixed / na / accepted / gap
  - **for 20 rows of your choice spanning V1–V17: the requirement, the evidence line's actual code, and the specific assertion in the cited test that would fail without the control.** The PM will independently sample 15 more.
- `pre-commit run --all-files`, `just security` and `just api-drift` exit 0. `just check` runs **last**; paste its unfiltered tail.
