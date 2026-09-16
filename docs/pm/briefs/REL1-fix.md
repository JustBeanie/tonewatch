# Brief: REL1-fix — invalid reusable-workflow `uses:`, a missed checkout, and a direct `${{ }}` in `run:`

**From:** PM (Claude) · **To:** Codex engineer (resume thread `01a0ac0a-6242-75b3-ba38-db7144dfd8eb`) · **Model:** gpt-5.6-luna, medium
**Work dir:** worktree `tonewatch-rel1`. **E2E port:** `TONEWATCH_E2E_PORT=8818`. Environment and git rules are the same as REL1.

## Verdict on REL1: FAIL
**PM verified and kept:**
- The `workflow_call` input, tag-aware concurrency, and the `attach` job gated on `inputs.release_tag != ''` with `needs` on all four verification jobs.
- Tag validation, rename plus `SHA256SUMS.txt`, and `contents: write` on `attach` only.
- The release-please `extra-files` fix: the path is package-relative, and the `@.name.value` selector matches release-please issue #2561.
- `check_lock_version.py`, its mismatch test, and the `just check` wiring.

**Why it fails:**
1. **`release.yml:118` uses `uses: $/.github/workflows/windows.yml`. That isn't valid GitHub syntax; the release job would error at workflow load.**
   - The PM ran actionlint 1.7.7, which reports: `reusable workflow call "$/.github/workflows/windows.yml" at "uses" is not following the format "owner/repo/path/to/workflow.yml@ref" nor "./path/to/workflow.yml"`.
   - GitHub documents a same-repository reusable workflow as `uses: ./.github/workflows/<file>.yml`.
   - The claim that zizmor documents `$/...` as a replacement was not verified and is wrong for GitHub Actions. Don't cite documentation you didn't read. If a source is unclear, say so.
2. **`service-lifecycle` (its `actions/checkout` at around `windows.yml:133`) still checks out the default ref.** The brief required `ref:` in **every** job that checks out code. A release build would verify the service lifecycle against `main`, not the tag.
3. **`attach` interpolates `${{ github.repository }}` directly inside `run:`.** The brief said to pass values via `env:` only. Add `REPO: ${{ github.repository }}` to the job env and use `"$REPO"`.

## Required
- Fix items 1–3. Change nothing else.
- **Run actionlint yourself.** The PM built it at `C:\Users\beanie\AppData\Local\Temp\claude\C--Users-beanie-Documents-claude\84fbbdaf-f9a6-4447-a9f1-4fd699a53ece\scratchpad\gobin\actionlint.exe`. Run it on `.github/workflows/release.yml .github/workflows/windows.yml` and paste the full output (it must be empty with rc 0). If that path isn't readable from your sandbox, say so explicitly; don't claim it passed.
- Grep proof: `rg -n "actions/checkout" -A3 .github/workflows/windows.yml`, showing `ref:` under every checkout. Also `rg -n '\$\{\{' .github/workflows/windows.yml`, showing no `${{` inside any `run:` block of `attach`.
- `just check` (paste the final lines). Skip ci-local; the PM runs it when landing.

## Standing rules
- Never edit `docs/pm/**` or `PLAN.md`. Never write git state. No new dependencies or actions.
- **Honesty rule:** don't describe work you haven't done, and don't cite sources you didn't read.
