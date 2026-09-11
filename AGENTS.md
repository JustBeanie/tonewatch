# AGENTS.md

Instructions for autonomous coding agents working on this repo. The full spec is in `PLAN.md`; progress is tracked in `docs/PROGRESS.md`.

1. **Resume protocol.** Read `PLAN.md` and `docs/PROGRESS.md`. Pick the **lowest-numbered unchecked task whose dependencies are done** and that is not marked 🛑 or `BLOCKED-ON-USER`.
2. **One task means one branch** (`m2.3-segmenter`) and **one PR** with a Conventional Commit title that includes the task ID. Keep PRs small, under about 600 changed lines excluding lockfiles and generated files.
3. **Test-first for `dsp/`, `pipeline/` and `alerts/`.** Write the failing test, then the code.
4. **Before committing, run `just check`.** It must be green. Never use `--no-verify`, never lower coverage gates, and never add `# type: ignore`, `# noqa` or `eslint-disable` without a same-line justification comment.
5. **Never:**
   - commit secrets or real radio recordings
   - run `gh-bootstrap.sh`, push to GHCR, create repos, or publish releases
   - edit `PLAN.md` decisions; propose changes in `docs/decisions/NNNN-*.md` instead
6. **Updating the log.** When a task is done, tick it in `PROGRESS.md` with the PR link and one line of notes. When blocked, add a `BLOCKED:` line with the exact question, then move to the next unblocked task.
7. **When uncertain about external behavior** (a PyAV encoder, Supervisor API, or HA entity schema), write a spike test or ADR proving it before building on it.
8. **Stop condition.** Stop when every non-gated task is checked, or when only 🛑/BLOCKED tasks remain. Then write a summary at the top of `PROGRESS.md`.

**Dependency order:** M0 → M1 → M2 → M3 → M4 → M5 → (M6 ∥ M7) → M8 → (M9 ∥ M10) → M11 → M12. M2 can start right after M1.1.

## Commands

Only use `just` recipes: `setup`, `lint`, `fmt`, `typecheck`, `test`, `test-web`, `e2e`, `bench`, `gen-api`, `check`, `dev`, `docker-build`, `compose-up`.

## Gates

Tasks marked 🛑 or `BLOCKED-ON-USER` need a human: M0.7 (GitHub repo creation/push), M8.4 (TTD config sample), M10 install on real HA, M12.4 release install. Prepare everything around them, but never perform them.

## Local mode (active until the GitHub repo exists — M0.7)

There is no remote yet, so the PR workflow is replaced by a PM review loop:

- Engineers (Codex agents) **do not run `git commit`, `git branch`, `git checkout` or `git stash`**. Leave all changes in the working tree.
- The PM (Claude) reviews the diff, runs `just check`, and commits one commit per task ID using the Conventional Commit title the PR would have had.
- The brief you were given (`docs/pm/briefs/<milestone>.md`) lists exactly which task IDs are in scope. Do not start tasks outside it.
- Anything you'd put in a PR description goes in your final message: what changed per task ID, how you verified it, open risks, and any `BLOCKED:` questions.
- CI can't run yet. Verify CI-only requirements locally where possible, and mark the rest `PENDING-CI` in `docs/PROGRESS.md` instead of ticking them.
- Tool caches live in the usual user dirs (uv, pnpm, npm, pre-commit), which are writable. Don't install anything system-wide.

### Tooling inside the Codex sandbox (Windows)

The sandbox runs as a separate user with a reduced PATH and **cannot see WinGet install folders**. The PM keeps working copies of the tools in the gitignored `.tools/bin` folder (`uv.exe`, `uvx.exe`, `just.exe`, `pnpm.cmd`). Start every shell command with:

```
set "PATH=%CD%\.tools\bin;C:\Program Files\nodejs;%PATH%" && <command>
```

**Never** install tools globally (npm -g, curl-downloading binaries, winget, pip --user). If a tool is missing, write `BLOCKED: need <tool>` and the PM will provision it.

**Never tick a task in `docs/PROGRESS.md` until its Definition of done has actually been run green.** If you can't run the verification, mark the task `[~]` with the reason.
