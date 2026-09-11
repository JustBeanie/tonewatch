# PM review: S1 fails. The assessment is placeholder content.

The validator, generator, tests and `just` wiring are good; keep them. The assessment data does not meet the brief.

## Findings, all required
1. **Placeholder questions.** All 30 SAMM entries use invented text like "Does the project perform the Strategy & Metrics activity for stream A?". The brief required the **official SAMM v2 assessment questions** and stream names.
   - Stream names include Secure Build A = *Build Process* and B = *Software Dependencies*, and Security Testing A = *Scalable Baseline* and B = *Deep Understanding*.
   - Get them from the `owaspsamm/core` repository on GitHub (the model YAML under `model/`, including the questions and answer options per stream and level), or from the SAMM toolbox.
   - Pin the commit SHA in `docs/security/samm/README.md`.
   - Each entry must carry: stream name, the official question per level, the official answer option chosen, and a short rationale.
2. **Under-scoring is as wrong as over-scoring.** Everything is 0 with zero evidence, but evidence exists **today** and is now live on GitHub (`JustBeanie/tonewatch`, private). Score each of these against the official answer options:
   - Secure Build A (Build Process): `.github/workflows/ci.yml`, a defined and automated build; actions pinned to full SHAs; the `justfile`.
   - Secure Build B (Software Dependencies): `backend/uv.lock`, `web/pnpm-lock.yaml`, `renovate.json`, and Dependabot alerts enabled on the repo.
   - Security Testing A (Scalable Baseline): `.github/workflows/codeql.yml`, ruff `S` (bandit) rules in `backend/pyproject.toml`, and pre-commit hooks.
   - Policy & Compliance / Strategy: `SECURITY.md`, `PLAN.md` "Security assurance" section, `docs/security/README.md`.
   - Security Requirements A: `PLAN.md` security requirements (script hook off by default, HMAC webhooks, SSRF blocking, auth token, ASVS L2 target).
   - Defect Management A: GitHub issue labels `security` and `area:security` now exist; `gaps.md` tracks findings.
   - Implementation / Test & Verification DSOMM activities that these files satisfy must be `implemented` or `partial`, with that evidence.
3. **N/A misuse.** Incident Management is marked N/A, but the PLAN target is **Level 1 in all 15 practices**. N/A is only for activities that genuinely can't apply to a solo open-source self-hosted project, and Incident Management does apply (`SECURITY.md` disclosure handling, a GitHub security advisory process). Re-score it. Review Education & Guidance the same way: Level 1 can be met by `CONTRIBUTING.md` and `AGENTS.md` secure-coding rules if they contain such guidance. If they don't, it's a gap, not N/A.
4. **Validator hardening.**
   - `security_scorecard.py` must fail when a question field doesn't match the pinned official model text. Load the pinned model file, vendored under `docs/security/samm/model/` with its licence noted.
   - It must also fail when a non-N/A entry has `current_level > 0` without evidence.
   - Add tests for both.
5. **Portability bug** (inherited from M0, but you touched this file). `.pre-commit-config.yaml` hard-codes `C:/Users/beanie/Documents/Proj/tonewatch/.tools/bin/uv.exe`, `cmd.exe` and `--python 3.13.13`. These hooks break on CI, Linux and any other clone. Make the hooks portable: call `uv` from PATH, and on Windows rely on the documented PATH prefix. No absolute paths, no patch-version pin.

## Definition of done
- `just check` exits 0.
- pre-commit over all files exits 0 with no unexpected skips.
- The final message includes the revised SAMM table (current vs target per function) with **at least the evidence-backed entries above scored**, the DSOMM counts, the pinned SAMM commit, and 5 example entries quoting official question and answer text.
