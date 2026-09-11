# PM review, round 2: pre-commit never actually checked anything

`just setup` and `just check` now pass. PM re-verified both. Good work.

However, your "pre-commit passed" evidence was hollow. `pre-commit run --all-files` only sees **git-tracked** files, and nothing was tracked, so ruff, prettier, yamllint and the others all reported `(no files to check) Skipped`. The PM has now staged every file (`git add -A`; don't commit). The real run fails.

## Findings, all required
1. **prettier hook (exit 2).** The hook runs from the repo root but hands Prettier `web/...` paths while running inside `web/`, so it fails with `No files matching the pattern were found: "web/src/App.tsx"`. Fix the hook's working directory and path handling so it works on Windows and Linux. Also exclude `pnpm-lock.yaml` and other generated files from Prettier.
2. **shellcheck on `scripts/gh-bootstrap.sh` (SC2102).** Quote the `-f 'security_and_analysis[secret_scanning][status]=enabled'` style arguments.
3. **Coverage gates.** `PLAN.md` requires ≥95% for `dsp/` and `pipeline/` on top of 85% overall. Those packages don't exist yet, but add the mechanism now: a small `backend/scripts/check_package_coverage.py` run by `just test` that reads `coverage.json`, and skips packages that don't exist yet. That way M2 can't forget it.
4. **`.pytest_cache` ownership.** It was created by the sandbox user and is not writable by the normal user (`WinError 5`). Set `cache_dir` under `backend/.pytest_cache` (gitignored), or pass `-p no:cacheprovider` in CI only. Pick one and document it. Do not change ACLs.

## Rule for all future verification
- Run pre-commit as `uv run --project backend pre-commit run --all-files` **after confirming files are staged**.
- If `git add` is denied in the sandbox, use `pre-commit run --files <every file from git ls-files -co --exclude-standard>`.
- Any hook that prints `(no files to check)` on a hook that should have matched counts as a **failure of verification**, not a pass.

## Definition of done
`just check` exits 0, and pre-commit over all files exits 0 with **no unexpected Skipped hooks**. Paste the full, unfiltered pre-commit output in your final message.
