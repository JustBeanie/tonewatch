# Brief: M10a-rebase-resume — continue after host interruption

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high (resume of your M10a thread)
**Work dir:** worktree `tonewatch-m10a`

Your previous run was killed by a host restart at 09:17:46, while you were running `just --set TONEWATCH_E2E_PORT 8792 e2e`. The worktree is as you left it.

1. Run `git status` and check that no conflict markers remain: `rg -n "^(<<<<<<<|=======|>>>>>>>)" backend web docs scripts .github`.
2. Finish `docs/pm/briefs/M10a-rebase.md` and meet its definition of done.
3. Re-run the gates you had not yet confirmed.
   - Use port 8792 for e2e.
   - If the Windows Playwright launcher only fails during teardown after every scenario passed, report that exactly. The PM re-runs e2e on the host.
4. The standing rules still apply:
   - no `docs/pm/**` edits
   - no weakened gates
   - no git network operations or commits
5. Your final message lists each conflicted file and how you combined both sides, plus the gate tails.
